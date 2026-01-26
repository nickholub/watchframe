# Apple Watch Video Framer

Wrap Apple Watch screen recordings and screenshots in a device frame for presentation-ready output.

## Installation

```bash
pip install -r requirements.txt
```

## Setup

Download watch frames from [Apple Design Resources](https://developer.apple.com/design/resources/#product-bezels):

1. Download "Apple Watch Ultra 2" bezels
2. Extract and copy the `PNG/` folder to this project's root directory

## Usage

### Frame a video

```bash
python3 frame_video.py -s recording.mov
```

### Frame an image

```bash
python3 frame_video.py -s screenshot.png
```

### Custom frame and output

```bash
python3 frame_video.py -s input.mov -f custom_frame.png -o output.mp4
```

### Manual screen positioning

If auto-detection doesn't find the correct screen area:

```bash
python3 frame_video.py -s recording.mov --screen-x 95 --screen-y 219 --screen-width 410 --screen-height 502
```

## How It Works

1. Loads the watch frame PNG (must have transparent screen area)
2. Detects the screen region via connected component analysis on the alpha channel
3. Scales and centers the source media to fit the screen bounds
4. Composites frames with alpha blending
5. Outputs MP4 (video) or PNG (image)

## Watch Frame Requirements

- PNG format with alpha channel (RGBA)
- Screen area must be transparent (alpha < 10)
- Frame should have the watch body/bezel as opaque pixels

## Supported Formats

**Images:** `.png`, `.jpg`, `.jpeg`, `.bmp`, `.tiff`, `.webp`

**Videos:** `.mov`, `.mp4`, `.avi`, `.mkv`, `.webm`, `.m4v`

## License

MIT
