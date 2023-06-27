#!/usr/bin/env python3
""" Sorting methods that use the properties of a :class:`lib.align.AlignedFace` object to obtain
their sorting metrics.
"""
from __future__ import annotations
import logging
import operator
import sys
import typing as T

import numpy as np
from tqdm import tqdm

from lib.align import AlignedFace
from lib.utils import FaceswapError
from .sort_methods import SortMethod

if T.TYPE_CHECKING:
    from argparse import Namespace
    from lib.align.alignments import PNGHeaderAlignmentsDict

logger = logging.getLogger(__name__)


class SortAlignedMetric(SortMethod):  # pylint:disable=too-few-public-methods
    """ Sort by comparison of metrics stored in an Aligned Face objects. This is a parent class
    for sort by aligned metrics methods. Individual methods should inherit from this class

    Parameters
    ----------
    arguments: :class:`argparse.Namespace`
        The command line arguments passed to the sort process
    sort_reverse: bool, optional
        ``True`` if the sorted results should be in reverse order. Default: ``True``
    is_group: bool, optional
        Set to ``True`` if this class is going to be called exclusively for binning.
        Default: ``False``
    """
    def _get_metric(self, aligned_face: AlignedFace) -> np.ndarray | float:
        """ Obtain the correct metric for the given sort method"

        Parameters
        ----------
        aligned_face: :class:`lib.align.AlignedFace`
            The aligned face to extract the metric from

        Returns
        -------
        float or :class:`numpy.ndarray`
            The metric for the current face based on chosen sort method
        """
        raise NotImplementedError

    def sort(self) -> None:
        """ Sort by metric score. Order in reverse for distance sort. """
        logger.info("Sorting...")
        self._result = sorted(self._result, key=operator.itemgetter(1), reverse=True)

    def score_image(self,
                    filename: str,
                    image: np.ndarray | None,
                    alignments: PNGHeaderAlignmentsDict | None) -> None:
        """ Score a single image for sort method: "distance", "yaw", "pitch" or "size" and add the
        result to :attr:`_result`

        Parameters
        ----------
        filename: str
            The filename of the currently processing image
        image: :class:`np.ndarray` or ``None``
            A face image loaded from disk or ``None``
        alignments: dict or ``None``
            The alignments dictionary for the aligned face or ``None``
        """
        if self._log_once:
            msg = "Grouping" if self._is_group else "Sorting"
            logger.info("%s by %s...", msg, self._method)
            self._log_once = False

        if not alignments:
            msg = ("The images to be sorted do not contain alignment data. Images must have "
                   "been generated by Faceswap's Extract process.\nIf you are sorting an "
                   "older faceset, then you should re-extract the faces from your source "
                   "alignments file to generate this data.")
            raise FaceswapError(msg)

        face = AlignedFace(np.array(alignments["landmarks_xy"], dtype="float32"))
        self._result.append((filename, self._get_metric(face)))


class SortDistance(SortAlignedMetric):
    """ Sorting mechanism for sorting faces from small to large """
    def _get_metric(self, aligned_face: AlignedFace) -> float:
        """ Obtain the distance from mean face metric for the given face

        Parameters
        ----------
        aligned_face: :class:`lib.align.AlignedFace`
            The aligned face to extract the metric from

        Returns
        -------
        float
            The distance metric for the current face
        """
        return aligned_face.average_distance

    def sort(self) -> None:
        """ Override default sort to sort in ascending order. """
        logger.info("Sorting...")
        self._result = sorted(self._result, key=operator.itemgetter(1), reverse=False)

    def binning(self) -> list[list[str]]:
        """ Create bins to split linearly from the lowest to the highest sample value

        Returns
        -------
        list
            List of bins of filenames
        """
        return self._binning_linear_threshold(multiplier=100)


class SortPitch(SortAlignedMetric):
    """ Sorting mechansim for sorting a face by pitch (down to up) """
    def _get_metric(self, aligned_face: AlignedFace) -> float:
        """ Obtain the pitch metric for the given face

        Parameters
        ----------
        aligned_face: :class:`lib.align.AlignedFace`
            The aligned face to extract the metric from

        Returns
        -------
        float
            The pitch metric for the current face
        """
        return aligned_face.pose.pitch

    def binning(self) -> list[list[str]]:
        """ Create bins from 0 degrees to 180 degrees based on number of bins

        Allocate item to bin when it is in range of one of the pre-allocated bins

        Returns
        -------
        list
            List of bins of filenames
        """
        thresholds = np.linspace(90, -90, self._num_bins + 1)

        # Start bin names from 0 for more intuitive experience
        names = np.flip(thresholds.astype("int")) + 90
        self._bin_names = [f"{self._method}_"
                           f"{idx:03d}_{int(names[idx])}"
                           f"degs_to_{int(names[idx + 1])}degs"
                           for idx in range(self._num_bins)]

        bins: list[list[str]] = [[] for _ in range(self._num_bins)]
        for filename, result in self._result:
            result = np.clip(result, -90.0, 90.0)
            bin_idx = next(bin_id for bin_id, thresh in enumerate(thresholds)
                           if result >= thresh) - 1
            bins[bin_idx].append(filename)
        return bins


class SortYaw(SortPitch):
    """ Sorting mechansim for sorting a face by yaw (left to right). Same logic as sort pitch, but
    with different metric """
    def _get_metric(self, aligned_face: AlignedFace) -> float:
        """ Obtain the yaw metric for the given face

        Parameters
        ----------
        aligned_face: :class:`lib.align.AlignedFace`
            The aligned face to extract the metric from

        Returns
        -------
        float
            The yaw metric for the current face
        """
        return aligned_face.pose.yaw


class SortRoll(SortPitch):
    """ Sorting mechansim for sorting a face by roll (rotation). Same logic as sort pitch, but
    with different metric """
    def _get_metric(self, aligned_face: AlignedFace) -> float:
        """ Obtain the roll metric for the given face

        Parameters
        ----------
        aligned_face: :class:`lib.align.AlignedFace`
            The aligned face to extract the metric from

        Returns
        -------
        float
            The yaw metric for the current face
        """
        return aligned_face.pose.roll


class SortSize(SortAlignedMetric):
    """ Sorting mechanism for sorting faces from small to large """
    def _get_metric(self, aligned_face: AlignedFace) -> float:
        """ Obtain the size metric for the given face

        Parameters
        ----------
        aligned_face: :class:`lib.align.AlignedFace`
            The aligned face to extract the metric from

        Returns
        -------
        float
            The size metric for the current face
        """
        roi = aligned_face.original_roi
        size = ((roi[1][0] - roi[0][0]) ** 2 + (roi[1][1] - roi[0][1]) ** 2) ** 0.5
        return size

    def binning(self) -> list[list[str]]:
        """ Create bins to split linearly from the lowest to the highest sample value

        Allocate item to bin when it is in range of one of the pre-allocated bins

        Returns
        -------
        list
            List of bins of filenames
        """
        return self._binning_linear_threshold(units="px")


class SortFaceCNN(SortAlignedMetric):
    """ Sort by landmark similarity or dissimilarity

    Parameters
    ----------
    arguments: :class:`argparse.Namespace`
        The command line arguments passed to the sort process
    is_group: bool, optional
        Set to ``True`` if this class is going to be called exclusively for binning.
        Default: ``False``
    """
    def __init__(self, arguments: Namespace, is_group: bool = False) -> None:
        super().__init__(arguments, is_group=is_group)
        self._is_dissim = self._method == "face-cnn-dissim"
        self._threshold: float = 7.2 if arguments.threshold < 1.0 else arguments.threshold

    def _get_metric(self, aligned_face: AlignedFace) -> np.ndarray:
        """ Obtain the xy aligned landmarks for the face"

        Parameters
        ----------
        aligned_face: :class:`lib.align.AlignedFace`
            The aligned face to extract the metric from

        Returns
        -------
        float
            The metric for the current face based on chosen sort method
        """
        return aligned_face.landmarks

    def sort(self) -> None:
        """ Sort by landmarks. """
        logger.info("Comparing landmarks and sorting...")
        if self._is_dissim:
            self._sort_landmarks_dissim()
            return
        self._sort_landmarks_ssim()

    def _sort_landmarks_ssim(self) -> None:
        """ Sort landmarks by similarity """
        img_list_len = len(self._result)
        for i in tqdm(range(0, img_list_len - 1), desc="Comparing", file=sys.stdout, leave=False):
            min_score = float("inf")
            j_min_score = i + 1
            for j in range(i + 1, img_list_len):
                fl1 = self._result[i][1]
                fl2 = self._result[j][1]
                score = np.sum(np.absolute((fl2 - fl1).flatten()))
                if score < min_score:
                    min_score = score
                    j_min_score = j
            (self._result[i + 1], self._result[j_min_score]) = (self._result[j_min_score],
                                                                self._result[i + 1])

    def _sort_landmarks_dissim(self) -> None:
        """ Sort landmarks by dissimilarity """
        logger.info("Comparing landmarks...")
        img_list_len = len(self._result)
        for i in tqdm(range(0, img_list_len - 1), desc="Comparing", file=sys.stdout, leave=False):
            score_total = 0
            for j in range(i + 1, img_list_len):
                if i == j:
                    continue
                fl1 = self._result[i][1]
                fl2 = self._result[j][1]
                score_total += np.sum(np.absolute((fl2 - fl1).flatten()))
            self._result[i][2] = score_total

        logger.info("Sorting...")
        self._result = sorted(self._result, key=operator.itemgetter(2), reverse=True)

    def binning(self) -> list[list[str]]:
        """ Group into bins by CNN face similarity

        Returns
        -------
        list
            List of bins of filenames
        """
        msg = "dissimilarity" if self._is_dissim else "similarity"
        logger.info("Grouping by face-cnn %s...", msg)

        # Groups are of the form: group_num -> reference faces
        reference_groups: dict[int, list[np.ndarray]] = {}

        # Bins array, where index is the group number and value is
        # an array containing the file paths to the images in that group.
        bins: list[list[str]] = []

        # Comparison threshold used to decide how similar
        # faces have to be to be grouped together.
        # It is multiplied by 1000 here to allow the cli option to use smaller
        # numbers.
        threshold = self._threshold * 1000
        img_list_len = len(self._result)

        for i in tqdm(range(0, img_list_len - 1),
                      desc="Grouping",
                      file=sys.stdout,
                      leave=False):
            fl1 = self._result[i][1]

            current_key = -1
            current_score = float("inf")

            for key, references in reference_groups.items():
                try:
                    score = self._get_avg_score(fl1, references)
                except TypeError:
                    score = float("inf")
                except ZeroDivisionError:
                    score = float("inf")
                if score < current_score:
                    current_key, current_score = key, score

            if current_score < threshold:
                reference_groups[current_key].append(fl1[0])
                bins[current_key].append(self._result[i][0])
            else:
                reference_groups[len(reference_groups)] = [self._result[i][1]]
                bins.append([self._result[i][0]])

        return bins

    @classmethod
    def _get_avg_score(cls, face: np.ndarray, references: list[np.ndarray]) -> float:
        """ Return the average CNN similarity score between a face and reference images

        Parameters
        ----------
        face: :class:`numpy.ndarray`
            The face to check against reference images
        references: list
            List of reference arrays to compare the face against

        Returns
        -------
        float
            The average score between the face and the references
        """
        scores = []
        for ref in references:
            score = np.sum(np.absolute((ref - face).flatten()))
            scores.append(score)
        return sum(scores) / len(scores)
