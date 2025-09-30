"""
DHPR (Driving-Hazard-Prediction-and-Reasoning) dataset loader.

This module provides functions to load the DHPR dataset from HuggingFace
with full multimodal support, including base64-encoded images in structured
content format (OpenAI style).

Dataset: https://huggingface.co/datasets/DHPR/Driving-Hazard-Prediction-and-Reasoning
"""

import opik
from typing import List, Dict, Any, Optional
from PIL import Image

# Import our image utilities
from opik_optimizer.utils.image_helpers import (
    encode_pil_to_base64_uri,
    convert_to_structured_content,
)


def driving_hazard_50(test_mode: bool = False) -> opik.Dataset:
    """
    Dataset containing 50 samples from the DHPR driving hazard dataset.

    Each sample includes:
    - question: The hazard detection question
    - image_content: Structured content with text and base64-encoded image
    - hazard: Expected hazard description (ground truth)
    - question_id: Unique identifier

    Args:
        test_mode: If True, creates a test dataset with only 5 samples

    Returns:
        opik.Dataset with multimodal hazard detection samples
    """
    return _load_dhpr_dataset(
        dataset_name_prefix="driving_hazard_50",
        nb_items=50,
        test_mode=test_mode,
        split="train",
    )


def driving_hazard_100(test_mode: bool = False) -> opik.Dataset:
    """
    Dataset containing 100 samples from the DHPR driving hazard dataset.

    Args:
        test_mode: If True, creates a test dataset with only 5 samples

    Returns:
        opik.Dataset with multimodal hazard detection samples
    """
    return _load_dhpr_dataset(
        dataset_name_prefix="driving_hazard_100",
        nb_items=100,
        test_mode=test_mode,
        split="train",
    )


def driving_hazard_test(test_mode: bool = False) -> opik.Dataset:
    """
    Dataset containing samples from the DHPR test split.

    Args:
        test_mode: If True, loads only 5 samples; otherwise loads 100 samples

    Returns:
        opik.Dataset with multimodal hazard detection samples
    """
    return _load_dhpr_dataset(
        dataset_name_prefix="driving_hazard_test",
        nb_items=100,
        test_mode=test_mode,
        split="test",
    )


def _load_dhpr_dataset(
    dataset_name_prefix: str,
    nb_items: int,
    test_mode: bool,
    split: str = "train",
    max_image_size: Optional[tuple[int, int]] = (800, 600),
) -> opik.Dataset:
    """
    Internal function to load DHPR dataset with multimodal support.

    Args:
        dataset_name_prefix: Prefix for the dataset name
        nb_items: Number of items to load
        test_mode: Whether to create a test dataset
        split: Dataset split to load ("train", "test", or "val")
        max_image_size: Maximum image size (width, height) for resizing.
            Set to None to keep original size.

    Returns:
        opik.Dataset with loaded and processed samples
    """
    # Adjust for test mode
    dataset_name = f"{dataset_name_prefix}" if not test_mode else f"{dataset_name_prefix}_test"
    actual_nb_items = nb_items if not test_mode else 5

    # Get or create dataset
    client = opik.Opik()
    dataset = client.get_or_create_dataset(dataset_name)

    # Check if dataset already has the correct number of items
    items = dataset.get_items()
    if len(items) == actual_nb_items:
        return dataset
    elif len(items) != 0:
        raise ValueError(
            f"Dataset {dataset_name} contains {len(items)} items, expected {actual_nb_items}. "
            f"We recommend deleting the dataset and re-creating it."
        )

    # Load from HuggingFace and process
    if len(items) == 0:
        import datasets as ds

        # Load DHPR dataset from HuggingFace
        download_config = ds.DownloadConfig(download_desc=False, disable_tqdm=True)
        ds.disable_progress_bar()

        try:
            hf_dataset = ds.load_dataset(
                "DHPR/Driving-Hazard-Prediction-and-Reasoning",
                streaming=True,
                download_config=download_config,
                trust_remote_code=True,  # May be needed for custom dataset scripts
            )
        except Exception as e:
            # Fallback: try without streaming if streaming fails
            try:
                hf_dataset = ds.load_dataset(
                    "DHPR/Driving-Hazard-Prediction-and-Reasoning",
                    download_config=download_config,
                    trust_remote_code=True,
                )
            except Exception as inner_e:
                ds.enable_progress_bar()
                raise ValueError(
                    f"Failed to load DHPR dataset: {inner_e}. "
                    f"Make sure you have internet connection and the dataset is accessible."
                )

        # Process items
        data: List[Dict[str, Any]] = []

        for i, item in enumerate(hf_dataset[split]):
            if i >= actual_nb_items:
                break

            try:
                processed_item = _process_dhpr_item(
                    item=item,
                    max_image_size=max_image_size,
                )
                data.append(processed_item)
            except Exception as e:
                # Log error but continue processing
                print(f"Warning: Failed to process item {i}: {e}")
                continue

        ds.enable_progress_bar()

        if len(data) == 0:
            raise ValueError(
                f"No items were successfully processed from the DHPR dataset. "
                f"Please check the dataset format and image processing."
            )

        # Insert into Opik dataset
        dataset.insert(data)

        return dataset


def _process_dhpr_item(
    item: Dict[str, Any],
    max_image_size: Optional[tuple[int, int]],
) -> Dict[str, Any]:
    """
    Process a single DHPR item to create multimodal content.

    Args:
        item: Raw item from HuggingFace dataset
        max_image_size: Maximum image size for resizing

    Returns:
        Processed item with structured content
    """
    # Extract fields
    question_id = item.get("question_id", f"unknown_{hash(str(item))}")
    question = item.get("question", "What hazards do you see in this image?")
    hazard = item.get("hazard", "")
    image_obj = item.get("image")

    # Process image
    if image_obj is None:
        raise ValueError(f"Item {question_id} has no image")

    # Convert HuggingFace image to PIL Image if needed
    if hasattr(image_obj, "convert"):
        # Already a PIL Image
        pil_image = image_obj
    elif isinstance(image_obj, dict) and "bytes" in image_obj:
        # Image stored as bytes
        from io import BytesIO
        pil_image = Image.open(BytesIO(image_obj["bytes"]))
    else:
        # Try to convert directly
        pil_image = Image.open(image_obj)

    # Resize if needed
    if max_image_size:
        pil_image.thumbnail(max_image_size, Image.Resampling.LANCZOS)

    # Encode to base64 data URI
    image_uri = encode_pil_to_base64_uri(
        image=pil_image,
        format="JPEG",  # Use JPEG for dashcam photos to reduce size
        quality=85,
    )

    # Create structured content (OpenAI format)
    # This will be used as input to the model
    image_content = convert_to_structured_content(
        text=question,
        image_uri=image_uri,
        image_detail="auto",
    )

    # Return processed item
    # The optimizer will use:
    # - question: As the text prompt
    # - image_content: As multimodal structured content
    # - hazard: As the expected output for evaluation
    return {
        "question_id": question_id,
        "question": question,
        "image_content": image_content,  # Structured content with image
        "image_uri": image_uri,  # Direct image URI for reference
        "hazard": hazard,  # Expected output (ground truth)
    }
