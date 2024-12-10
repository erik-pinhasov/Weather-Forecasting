import pytest
import numpy as np
import torch
from PIL import Image
from data.dataset import SemanticSegmentationDataset


class MockFeatureExtractor:
    def __call__(self, image, mask, return_tensors="pt"):
        return {
            # Convert to CxHxW
            "pixel_values": torch.tensor(image, dtype=torch.float32).permute(2, 0, 1),
            "labels": torch.tensor(mask, dtype=torch.long)
        }


class MockTransform:
    def __call__(self, image, mask):
        # Flip and ensure positive strides by copying the array
        image = np.flip(image, axis=1).copy()
        mask = np.flip(mask, axis=1).copy()
        return {"image": image, "mask": mask}


@pytest.fixture
def mock_data():
    data = []
    for _ in range(5):
        image = Image.fromarray(np.random.randint(
            0, 256, (512, 512, 3), dtype=np.uint8))
        mask = Image.fromarray(np.random.randint(
            0, 2, (512, 512), dtype=np.uint8))  # Binary mask
        data.append({"image": image, "mask": mask})
    return data


@pytest.fixture
def feature_extractor():
    return MockFeatureExtractor()


def test_dataset_length(mock_data, feature_extractor):
    dataset = SemanticSegmentationDataset(
        data=mock_data, feature_extractor=feature_extractor)
    assert len(dataset) == len(mock_data)


@pytest.mark.parametrize("use_transform", [False, True])
def test_getitem_with_and_without_transform(mock_data, feature_extractor, use_transform):
    transform = MockTransform() if use_transform else None
    dataset = SemanticSegmentationDataset(
        data=mock_data, feature_extractor=feature_extractor, transform=transform
    )
    sample = dataset[0]
    assert "pixel_values" in sample
    assert "labels" in sample
    assert sample["pixel_values"].shape == (3, 512, 512)
    assert sample["labels"].shape == (512, 512)