# util/metric.py
from tqdm import tqdm
from torchmetrics import MetricCollection, JaccardIndex, Dice, Accuracy, Precision, Recall
import torch
import torch.nn as nn
from typing import Optional
import numpy as np
from core.errors import FocalAlphaSizeError, FocalAlphaTypeError, NormalizeError


class FocalLoss(nn.CrossEntropyLoss):
    """
        Focal Loss for addressing class imbalance in classification tasks.

        Args:
            num_classes (int): Number of classes.
            gamma (float, optional): Focusing parameter. Defaults to 2.0.
            alpha (float, list, np.ndarray, torch.Tensor, optional): Weighting factor for each class. Defaults to None.
            ignore_index (int, optional): Specifies a target value that is ignored and does not contribute to the input gradient. Defaults to None.
            reduction (str, optional): Specifies the reduction to apply to the output. Defaults to 'mean'.

        Attributes:
            ignore_index (int): The index to ignore in the target.
            gamma (float): The focusing parameter.
            reduction (str): The reduction method to apply to the output.
            num_classes (int): The number of classes.
            alpha (torch.Tensor): The weighting factor for each class.

        Raises:
            FocalAlphaTypeError: If the alpha type is unsupported.
            FocalAlphaSizeError: If alpha does not match `num_classes`.
    """

    def __init__(self, num_classes, gamma=2.0, alpha=None, ignore_index=None, reduction='mean'):
        self.ignore_index = ignore_index if ignore_index is not None else -100
        super().__init__(ignore_index=self.ignore_index, reduction='none')
        self.gamma = gamma
        self.reduction = reduction
        self.num_classes = num_classes
        self.alpha = self.__set_alpha__(alpha)

    def forward(self, input_, target):
        self.alpha = self.alpha.to(input_.device)
        cross_entropy = super().forward(input_, target)
        pt = torch.exp(-cross_entropy)
        at = self.alpha[target]

        loss = at * ((1-pt)**self.gamma) * cross_entropy

        valid_mask = (target != self.ignore_index)
        valid_loss = loss[valid_mask]

        if self.reduction == 'mean':
            return valid_loss.mean()
        elif self.reduction == 'sum':
            return valid_loss.sum()
        else:
            return loss

    def __set_alpha__(self, alpha):
        """
        Set the alpha value for class weighting.

        Args:
            alpha (float, list, np.ndarray, torch.Tensor, optional): Weighting factor for each class.

        Returns:
            torch.Tensor: The alpha tensor.

        Raises:
            FocalAlphaTypeError: If the alpha type is unsupported.
            FocalAlphaSizeError: alpha does not match num_classes.
        """
        if alpha is None:
            alpha_tensor = torch.ones(self.num_classes, dtype=torch.float)
        elif isinstance(alpha, (float, int)):
            alpha_tensor = torch.full(
                (self.num_classes,), alpha, dtype=torch.float)
        elif isinstance(alpha, (np.ndarray, list)):
            alpha_tensor = torch.tensor(alpha, dtype=torch.float)
        elif isinstance(alpha, torch.Tensor):
            alpha_tensor = alpha
        else:
            raise FocalAlphaTypeError(f"Unsupported alpha type: {type(alpha)}")

        if alpha_tensor.size(0) != self.num_classes:
            raise FocalAlphaSizeError(alpha_tensor.size(0), self.num_classes)

        return alpha_tensor


class SegMetrics(MetricCollection):
    """
    A utility class to handle metrics for segmentation tasks.
    Provides functionality for IoU (Jaccard Index) and Dice coefficient calculation.

    Args:
        num_classes (int): Number of classes in the segmentation task.
        device (str, optional): Device to run the metrics on. Default is "cpu".
        ignore_index (int, optional): Specifies a target value that is ignored and does not contribute to the input gradient. Default is None.

    Attributes:
        num_classes (int): The number of classes.
        ignore_index (int): The index to ignore in the target.
        metrics (dict): Dictionary of metrics to compute.
    """

    def __init__(self, num_classes, device="cpu", ignore_index: Optional[int] = None):
        self.num_classes = num_classes
        self.ignore_index = ignore_index
        self.metrics = {
            "mean_iou": JaccardIndex(task='multiclass', num_classes=num_classes, ignore_index=self.ignore_index).to(device),
            "mean_dice": Dice(average='micro', num_classes=num_classes, ignore_index=self.ignore_index).to(device)
        }
        super().__init__(self.metrics)

    def update(self, predicted: torch.Tensor, targets: torch.Tensor) -> None:
        predicted = predicted.view(-1)
        targets = targets.view(-1)

        super().update(predicted, targets)


class TestMetrics(SegMetrics):
    """
    A utility class to handle metrics for segmentation tasks.
    Provides functionality for IoU (Jaccard Index) and Dice coefficient calculation.

    Args:
        num_classes (int): Number of classes in the segmentation task.
        device (str, optional): Device to run the metrics on. Default is "cpu".
        ignore_index (int, optional): Specifies a target value that is ignored and does not contribute to the input gradient. Default is None.

    Attributes:
        num_classes (int): The number of classes.
        ignore_index (int): The index to ignore in the target.
        metrics (dict): Dictionary of metrics to compute.
    """

    def __init__(self, num_classes, device="cpu", ignore_index: Optional[int] = None):
        super().__init__(num_classes, device, ignore_index)
        test_metrics = {
            "accuracy": Accuracy(task="multiclass", num_classes=self.num_classes, average="macro", ignore_index=self.ignore_index).to(device),
            "precision": Precision(task="multiclass", num_classes=self.num_classes, average="macro", ignore_index=self.ignore_index).to(device),
            "recall": Recall(task="multiclass", num_classes=self.num_classes, average="macro", ignore_index=self.ignore_index).to(device),
        }
        self.add_metrics(test_metrics)


def compute_class_weights(train_dataloader, num_classes, mask_key="labels", normalize="balanced", ignore_index=None):
    """
    Compute class weights based on the frequencies of each class in the dataset.

    Args:
        train_dataloader (DataLoader): PyTorch DataLoader containing the dataset.
        num_classes (int): Total number of classes.
        mask_key (str): Key to access masks/labels in the dataloader's batch.
        normalize (str): "max" | "sum" | "balanced" Whether to normalize the weights.
        ignore_index (int, optional): Class index to ignore in weight computation.

    Returns:
        torch.Tensor: Computed class weights of shape (num_classes,).

    Raises:
        ValueError: If the normalization method is unsupported.
    """
    class_counts = torch.zeros(num_classes, dtype=torch.int64)

    for batch in tqdm(train_dataloader, desc="Compute class weights"):
        masks = batch[mask_key]
        masks = masks.view(-1)

        if ignore_index is not None:
            masks = masks[masks != ignore_index]

        counts = torch.bincount(masks, minlength=num_classes)
        class_counts += counts

    total_pixels = class_counts.sum().item()
    class_weights = total_pixels / (class_counts.float() + 1e-6)

    if ignore_index is not None:
        class_weights[ignore_index] = 0

    if normalize == "sum":
        class_weights /= class_weights.sum()
    elif normalize == "max":
        class_weights /= class_weights.max()
    elif normalize == "balanced":
        class_weights = (class_weights / class_weights.sum()
                         ) * (num_classes - 1)
    else:
        raise NormalizeError(normalize)

    return class_weights.to(torch.float32)
