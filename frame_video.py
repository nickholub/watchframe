#!/usr/bin/env python3
"""
Apple Watch Video Framer
Wraps an Apple Watch screen recording into a watch frame for presentation.
"""

import argparse
import sys
from pathlib import Path

try:
    import cv2
    import numpy as np
    from PIL import Image
except ImportError as e:
    print(f"Missing required package: {e}")
    print("Install with: pip install opencv-python pillow numpy")
    sys.exit(1)


def find_screen_area(frame_image):
    """
    Find the transparent (screen) area in the watch frame.
    Uses connected component analysis to find the screen area inside the bezel.
    Returns (x, y, width, height) of the bounding box.
    """
    # Convert to numpy array if needed
    if isinstance(frame_image, Image.Image):
        frame_array = np.array(frame_image)
    else:
        frame_array = frame_image

    # Get alpha channel
    if frame_array.shape[2] == 4:
        alpha = frame_array[:, :, 3]
    else:
        raise ValueError("Frame image must have an alpha channel (RGBA)")

    height, width = alpha.shape

    # Find transparent pixels (alpha < 10)
    transparent_mask = (alpha < 10).astype(np.uint8)

    # Find connected components of transparent areas
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        transparent_mask, connectivity=8
    )

    # Find the component closest to the center of the image
    # (the screen should be roughly centered, not at edges)
    center_x, center_y = width // 2, height // 2

    best_component = None
    best_distance = float('inf')
    min_area = 1000  # Minimum area to consider

    for i in range(1, num_labels):  # Skip background (label 0)
        area = stats[i, cv2.CC_STAT_AREA]
        if area < min_area:
            continue

        # Get centroid of this component
        cx, cy = centroids[i]

        # Calculate distance from image center
        distance = np.sqrt((cx - center_x) ** 2 + (cy - center_y) ** 2)

        # Prefer components that are more centered
        if distance < best_distance:
            best_distance = distance
            best_component = i

    if best_component is None:
        raise ValueError("No suitable transparent area found in frame image")

    # Get bounding box of the best component
    x = stats[best_component, cv2.CC_STAT_LEFT]
    y = stats[best_component, cv2.CC_STAT_TOP]
    w = stats[best_component, cv2.CC_STAT_WIDTH]
    h = stats[best_component, cv2.CC_STAT_HEIGHT]

    return x, y, w, h


def process_video(video_path, frame_path, output_path, screen_position=None):
    """
    Process video and wrap it in the watch frame.

    Args:
        video_path: Path to input .mov video
        frame_path: Path to watch frame PNG with transparency
        output_path: Path for output video
        screen_position: Optional tuple (x, y, width, height) for manual positioning
    """
    # Load the watch frame
    print(f"Loading watch frame: {frame_path}")
    watch_frame = Image.open(frame_path).convert('RGBA')
    frame_width, frame_height = watch_frame.size
    print(f"Frame dimensions: {frame_width}x{frame_height}")

    # Find or use screen area
    if screen_position:
        screen_x, screen_y, screen_w, screen_h = screen_position
    else:
        screen_x, screen_y, screen_w, screen_h = find_screen_area(watch_frame)
    print(f"Screen area: x={screen_x}, y={screen_y}, w={screen_w}, h={screen_h}")

    # Open input video
    print(f"Opening video: {video_path}")
    cap = cv2.VideoCapture(str(video_path))

    if not cap.isOpened():
        raise ValueError(f"Could not open video: {video_path}")

    # Get video properties
    fps = cap.get(cv2.CAP_PROP_FPS)
    video_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    video_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"Video dimensions: {video_width}x{video_height}")
    print(f"FPS: {fps}, Total frames: {total_frames}")

    # Calculate scaling to fit video into screen area
    scale_x = screen_w / video_width
    scale_y = screen_h / video_height
    scale = min(scale_x, scale_y)

    new_video_w = int(video_width * scale)
    new_video_h = int(video_height * scale)

    # Center the video in the screen area
    offset_x = screen_x + (screen_w - new_video_w) // 2
    offset_y = screen_y + (screen_h - new_video_h) // 2

    print(f"Scaled video: {new_video_w}x{new_video_h}")
    print(f"Position: ({offset_x}, {offset_y})")

    # Prepare output video writer
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(str(output_path), fourcc, fps, (frame_width, frame_height))

    # Convert watch frame to cv2 format (BGRA)
    watch_frame_cv = cv2.cvtColor(np.array(watch_frame), cv2.COLOR_RGBA2BGRA)

    # Process each frame
    frame_count = 0
    print("Processing frames...")

    while True:
        ret, video_frame = cap.read()
        if not ret:
            break

        frame_count += 1
        if frame_count % 30 == 0:
            print(f"Processing frame {frame_count}/{total_frames}")

        # Resize video frame
        video_frame_resized = cv2.resize(video_frame, (new_video_w, new_video_h))

        # Create base image (black background)
        composite = np.zeros((frame_height, frame_width, 3), dtype=np.uint8)

        # Place video frame at correct position
        composite[offset_y:offset_y + new_video_h, offset_x:offset_x + new_video_w] = video_frame_resized

        # Overlay watch frame using alpha compositing
        alpha = watch_frame_cv[:, :, 3:4] / 255.0
        watch_rgb = watch_frame_cv[:, :, :3]

        composite = (watch_rgb * alpha + composite * (1 - alpha)).astype(np.uint8)

        out.write(composite)

    cap.release()
    out.release()

    print(f"Done! Processed {frame_count} frames")
    print(f"Output saved to: {output_path}")


def process_image(image_path, frame_path, output_path, screen_position=None):
    """
    Process a single image and wrap it in the watch frame.

    Args:
        image_path: Path to input image
        frame_path: Path to watch frame PNG with transparency
        output_path: Path for output image
        screen_position: Optional tuple (x, y, width, height) for manual positioning
    """
    # Load the watch frame
    print(f"Loading watch frame: {frame_path}")
    watch_frame = Image.open(frame_path).convert('RGBA')
    frame_width, frame_height = watch_frame.size
    print(f"Frame dimensions: {frame_width}x{frame_height}")

    # Find or use screen area
    if screen_position:
        screen_x, screen_y, screen_w, screen_h = screen_position
    else:
        screen_x, screen_y, screen_w, screen_h = find_screen_area(watch_frame)
    print(f"Screen area: x={screen_x}, y={screen_y}, w={screen_w}, h={screen_h}")

    # Load input image
    print(f"Opening image: {image_path}")
    source_image = Image.open(image_path).convert('RGB')
    img_width, img_height = source_image.size
    print(f"Image dimensions: {img_width}x{img_height}")

    # Calculate scaling to fit image into screen area
    scale_x = screen_w / img_width
    scale_y = screen_h / img_height
    scale = min(scale_x, scale_y)

    new_img_w = int(img_width * scale)
    new_img_h = int(img_height * scale)

    # Center the image in the screen area
    offset_x = screen_x + (screen_w - new_img_w) // 2
    offset_y = screen_y + (screen_h - new_img_h) // 2

    print(f"Scaled image: {new_img_w}x{new_img_h}")
    print(f"Position: ({offset_x}, {offset_y})")

    # Resize source image
    source_resized = source_image.resize((new_img_w, new_img_h), Image.LANCZOS)

    # Create base image (black background)
    composite = Image.new('RGBA', (frame_width, frame_height), (0, 0, 0, 255))

    # Paste source image at correct position
    composite.paste(source_resized, (offset_x, offset_y))

    # Overlay watch frame using alpha compositing
    composite = Image.alpha_composite(composite, watch_frame)

    # Save output
    composite.save(output_path)
    print(f"Done! Output saved to: {output_path}")


def is_image_file(path):
    """Check if path is an image file based on extension."""
    image_extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp'}
    return path.suffix.lower() in image_extensions


def is_video_file(path):
    """Check if path is a video file based on extension."""
    video_extensions = {'.mov', '.mp4', '.avi', '.mkv', '.webm', '.m4v'}
    return path.suffix.lower() in video_extensions


def main():
    parser = argparse.ArgumentParser(
        description='Wrap Apple Watch screen recording in a watch frame'
    )
    parser.add_argument(
        '-s', '--source',
        help='Input video or image file'
    )
    parser.add_argument(
        '-f', '--frame',
        help='Watch frame PNG with transparent screen area (auto-detects if not specified)'
    )
    parser.add_argument(
        '-o', '--output',
        help='Output video path (default: input_framed.mp4)'
    )
    parser.add_argument(
        '--screen-x', type=int,
        help='Manual screen X position'
    )
    parser.add_argument(
        '--screen-y', type=int,
        help='Manual screen Y position'
    )
    parser.add_argument(
        '--screen-width', type=int,
        help='Manual screen width'
    )
    parser.add_argument(
        '--screen-height', type=int,
        help='Manual screen height'
    )

    args = parser.parse_args()

    # Show usage if no arguments provided
    if len(sys.argv) == 1:
        parser.print_help()
        print("\nExamples:")
        print("  python3 frame_video.py -s recording.mov")
        print("  python3 frame_video.py -s recording.mov -f frame.png")
        print("  python3 frame_video.py -s screenshot.png -f frame.png -o output.png")
        sys.exit(0)

    if not args.source:
        print("Error: -s/--source is required")
        sys.exit(1)

    source_path = Path(args.source)

    if args.frame:
        frame_path = Path(args.frame)
    else:
        # Use default frame from PNG folder
        script_dir = Path(__file__).parent
        default_frame = script_dir / "PNG" / "Milanese Loop" / "AW Ultra 2 - Black + Titanium Milanese Loop.png"
        if not default_frame.exists():
            print("Error: Default frame not found.")
            print("")
            print("To download Apple Watch frames:")
            print("  1. Visit https://developer.apple.com/design/resources/#product-bezels")
            print("  2. Download 'Apple Watch Ultra 2' bezels")
            print("  3. Extract and copy the PNG folder to this project's root folder")
            print("")
            print("Or specify a custom frame with -f argument.")
            sys.exit(1)
        frame_path = default_frame
        print(f"Using default frame: {frame_path.name}")

    # Determine if source is image or video
    is_image = is_image_file(source_path)
    is_video = is_video_file(source_path)

    if not is_image and not is_video:
        print(f"Error: Unsupported file type: {source_path.suffix}")
        print("Supported formats: .png, .jpg, .jpeg, .bmp, .tiff, .webp (images)")
        print("                   .mov, .mp4, .avi, .mkv, .webm, .m4v (videos)")
        sys.exit(1)

    # Set default output path based on source type
    if args.output:
        output_path = Path(args.output)
    else:
        if is_image:
            output_path = source_path.parent / f"{source_path.stem}_framed.png"
        else:
            output_path = source_path.parent / f"{source_path.stem}_framed.mp4"

    # Manual screen position if all parameters provided
    screen_position = None
    if all([args.screen_x is not None, args.screen_y is not None,
            args.screen_width, args.screen_height]):
        screen_position = (args.screen_x, args.screen_y,
                          args.screen_width, args.screen_height)

    # Process based on file type
    if is_image:
        process_image(source_path, frame_path, output_path, screen_position)
    else:
        process_video(source_path, frame_path, output_path, screen_position)


if __name__ == '__main__':
    main()
