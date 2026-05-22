#!/usr/bin/env python3
"""
watchframe - Wraps screenshots and recordings in an Apple device frame.
"""

import argparse
import sys
from pathlib import Path

try:
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw
except ImportError as e:
    print(f"Missing required package: {e}")
    print("Install with: pip install opencv-python pillow numpy")
    sys.exit(1)


def detect_screen_region(frame_image):
    """
    Find the transparent screen area in the device frame.
    Uses connected component analysis to find the interior screen aperture.
    Returns (x, y, width, height, mask) for the selected screen component.
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

    min_area = 1000  # Minimum area to consider
    candidates = []

    for i in range(1, num_labels):  # Skip background (label 0)
        area = stats[i, cv2.CC_STAT_AREA]
        if area < min_area:
            continue

        x = stats[i, cv2.CC_STAT_LEFT]
        y = stats[i, cv2.CC_STAT_TOP]
        w = stats[i, cv2.CC_STAT_WIDTH]
        h = stats[i, cv2.CC_STAT_HEIGHT]
        cx, cy = centroids[i]
        distance = np.sqrt((cx - center_x) ** 2 + (cy - center_y) ** 2)
        touches_edge = x <= 0 or y <= 0 or x + w >= width or y + h >= height
        candidates.append((i, touches_edge, distance))

    interior_candidates = [
        (component, distance)
        for component, touches_edge, distance in candidates
        if not touches_edge
    ]
    if interior_candidates:
        best_component = min(interior_candidates, key=lambda item: item[1])[0]
    elif candidates:
        best_component = min(candidates, key=lambda item: item[2])[0]
    else:
        best_component = None

    if best_component is None:
        raise ValueError("No suitable transparent area found in frame image")

    # Get bounding box of the best component
    x = stats[best_component, cv2.CC_STAT_LEFT]
    y = stats[best_component, cv2.CC_STAT_TOP]
    w = stats[best_component, cv2.CC_STAT_WIDTH]
    h = stats[best_component, cv2.CC_STAT_HEIGHT]

    component_mask = ((labels[y:y + h, x:x + w] == best_component) * 255).astype(np.uint8)

    return x, y, w, h, Image.fromarray(component_mask)


def find_screen_area(frame_image):
    """
    Find the transparent screen area in the device frame.
    Returns (x, y, width, height) of the bounding box.
    """
    return detect_screen_region(frame_image)[:4]


def make_rounded_screen_mask(width, height, corner_radius):
    """
    Create a smooth rounded-rectangle mask for the screen content.
    """
    scale = 4
    mask = Image.new('L', (width * scale, height * scale), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle(
        (0, 0, width * scale - 1, height * scale - 1),
        radius=corner_radius * scale,
        fill=255,
    )
    return mask.resize((width, height), Image.LANCZOS)


def get_screen_area_and_mask(frame_image, screen_position=None, corner_radius=None):
    """
    Return the screen bounds and alpha mask for the transparent screen opening.
    """
    if screen_position:
        screen_x, screen_y, screen_w, screen_h = screen_position
        frame_mask = Image.new('L', (screen_w, screen_h), 255)
    else:
        screen_x, screen_y, screen_w, screen_h, frame_mask = detect_screen_region(frame_image)

    screen_mask = frame_mask
    if corner_radius is not None:
        rounded_mask = make_rounded_screen_mask(screen_w, screen_h, corner_radius)
        screen_mask = Image.fromarray(
            np.minimum(np.array(frame_mask), np.array(rounded_mask)).astype(np.uint8)
        )

    return screen_x, screen_y, screen_w, screen_h, screen_mask


def render_source_to_screen(source_image, screen_size, fit):
    """
    Resize and crop/pad source content to the screen opening.
    """
    if fit not in ('cover', 'contain', 'stretch'):
        raise ValueError(f"Unsupported fit mode: {fit}")

    source_w, source_h = source_image.size
    screen_w, screen_h = screen_size

    if fit == 'stretch':
        return source_image.resize(screen_size, Image.LANCZOS)

    scale_x = screen_w / source_w
    scale_y = screen_h / source_h
    scale = max(scale_x, scale_y) if fit == 'cover' else min(scale_x, scale_y)
    if fit == 'cover':
        resized_w = max(screen_w, int(np.ceil(source_w * scale)))
        resized_h = max(screen_h, int(np.ceil(source_h * scale)))
    else:
        resized_w = max(1, int(round(source_w * scale)))
        resized_h = max(1, int(round(source_h * scale)))
    resized = source_image.resize((resized_w, resized_h), Image.LANCZOS)

    if fit == 'cover':
        left = max(0, (resized_w - screen_w) // 2)
        top = max(0, (resized_h - screen_h) // 2)
        return resized.crop((left, top, left + screen_w, top + screen_h))

    screen_content = Image.new('RGBA', screen_size, (0, 0, 0, 255))
    offset_x = (screen_w - resized_w) // 2
    offset_y = (screen_h - resized_h) // 2
    screen_content.alpha_composite(resized, (offset_x, offset_y))
    return screen_content


def paste_screen_image(composite, screen_image, screen_position, screen_mask):
    """
    Paste screen-sized source content into the transparent screen opening.
    """
    screen_x, screen_y, screen_w, screen_h = screen_position
    source_alpha = screen_image.getchannel('A')
    screen_alpha = Image.fromarray(
        np.minimum(np.array(source_alpha), np.array(screen_mask)).astype(np.uint8)
    )
    composite.paste(screen_image, (screen_x, screen_y), screen_alpha)


def warn_if_screen_mismatch(source_size, screen_size, fit):
    """
    Print a helpful warning when a screenshot doesn't match the bezel's screen.
    """
    if source_size == screen_size:
        return

    source_ratio = source_size[0] / source_size[1]
    screen_ratio = screen_size[0] / screen_size[1]
    print(
        "Warning: source dimensions "
        f"{source_size[0]}x{source_size[1]} do not match frame screen "
        f"{screen_size[0]}x{screen_size[1]}; using --fit {fit}."
    )
    if abs(source_ratio - screen_ratio) > 0.002:
        print(
            "         For a pixel-perfect result, use the bezel for the same "
            "device model as the screenshot or pass --fit stretch."
        )


def process_video(video_path, frame_path, output_path, screen_position=None, corner_radius=None, fit='cover'):
    """
    Process video and wrap it in the device frame.

    Args:
        video_path: Path to input .mov video
        frame_path: Path to device frame PNG with transparency
        output_path: Path for output video
        screen_position: Optional tuple (x, y, width, height) for manual positioning
        corner_radius: Optional screen corner radius in pixels
        fit: How to fit source media into the screen (cover, contain, stretch)
    """
    # Load the device frame
    print(f"Loading device frame: {frame_path}")
    device_frame = Image.open(frame_path).convert('RGBA')
    frame_width, frame_height = device_frame.size
    print(f"Frame dimensions: {frame_width}x{frame_height}")

    # Find or use screen area
    screen_x, screen_y, screen_w, screen_h, screen_mask = get_screen_area_and_mask(
        device_frame, screen_position, corner_radius
    )
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
    warn_if_screen_mismatch((video_width, video_height), (screen_w, screen_h), fit)

    print(f"Fit mode: {fit}")

    # Prepare output video writer
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(str(output_path), fourcc, fps, (frame_width, frame_height))

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

        video_rgb = cv2.cvtColor(video_frame, cv2.COLOR_BGR2RGB)
        source_image = Image.fromarray(video_rgb).convert('RGBA')
        screen_image = render_source_to_screen(source_image, (screen_w, screen_h), fit)

        composite = Image.new('RGBA', (frame_width, frame_height), (0, 0, 0, 255))
        paste_screen_image(
            composite,
            screen_image,
            (screen_x, screen_y, screen_w, screen_h),
            screen_mask,
        )
        composite = Image.alpha_composite(composite, device_frame)
        out.write(cv2.cvtColor(np.array(composite.convert('RGB')), cv2.COLOR_RGB2BGR))

    cap.release()
    out.release()

    print(f"Done! Processed {frame_count} frames")
    print(f"Output saved to: {output_path}")


def process_image(image_path, frame_path, output_path, screen_position=None, corner_radius=None, fit='cover'):
    """
    Process a single image and wrap it in the device frame.

    Args:
        image_path: Path to input image
        frame_path: Path to device frame PNG with transparency
        output_path: Path for output image
        screen_position: Optional tuple (x, y, width, height) for manual positioning
        corner_radius: Optional screen corner radius in pixels
        fit: How to fit source media into the screen (cover, contain, stretch)
    """
    # Load the device frame
    print(f"Loading device frame: {frame_path}")
    device_frame = Image.open(frame_path).convert('RGBA')
    frame_width, frame_height = device_frame.size
    print(f"Frame dimensions: {frame_width}x{frame_height}")

    # Find or use screen area
    screen_x, screen_y, screen_w, screen_h, screen_mask = get_screen_area_and_mask(
        device_frame, screen_position, corner_radius
    )
    print(f"Screen area: x={screen_x}, y={screen_y}, w={screen_w}, h={screen_h}")

    # Load input image
    print(f"Opening image: {image_path}")
    source_image = Image.open(image_path).convert('RGBA')
    img_width, img_height = source_image.size
    print(f"Image dimensions: {img_width}x{img_height}")
    warn_if_screen_mismatch((img_width, img_height), (screen_w, screen_h), fit)

    screen_image = render_source_to_screen(source_image, (screen_w, screen_h), fit)
    print(f"Rendered screen image: {screen_image.size[0]}x{screen_image.size[1]}")
    print(f"Position: ({screen_x}, {screen_y})")
    print(f"Fit mode: {fit}")

    composite = Image.new('RGBA', (frame_width, frame_height), (0, 0, 0, 0))

    # Paste the source behind the transparent screen opening.
    paste_screen_image(
        composite,
        screen_image,
        (screen_x, screen_y, screen_w, screen_h),
        screen_mask,
    )

    # Overlay the watch frame last so its alpha controls rounded edges and glass.
    composite = Image.alpha_composite(composite, device_frame)

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
        description='Wrap a screenshot or recording in an Apple device frame'
    )
    parser.add_argument(
        '-s', '--source',
        required=True,
        help='Input video or image file'
    )
    parser.add_argument(
        '-f', '--frame',
        required=True,
        help='Device frame PNG with transparent screen area'
    )
    parser.add_argument(
        '-o', '--output',
        help='Output path (default: input_framed.png or input_framed.mp4)'
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
    parser.add_argument(
        '--corner-radius', type=int,
        help='Optional source clipping radius in pixels; normally the frame alpha handles corners'
    )
    parser.add_argument(
        '--fit',
        choices=('cover', 'contain', 'stretch'),
        default='cover',
        help='How to fit source media into the screen opening (default: cover)'
    )

    args = parser.parse_args()

    source_path = Path(args.source)
    frame_path = Path(args.frame)

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
        process_image(
            source_path,
            frame_path,
            output_path,
            screen_position,
            args.corner_radius,
            args.fit,
        )
    else:
        process_video(
            source_path,
            frame_path,
            output_path,
            screen_position,
            args.corner_radius,
            args.fit,
        )


if __name__ == '__main__':
    main()
