"""Download the COCO MobileNet-SSD files used by semantic labeling."""

from __future__ import annotations

import argparse
import tarfile
import urllib.request
from pathlib import Path

MODEL_URL = "http://download.tensorflow.org/models/object_detection/ssd_mobilenet_v1_coco_2018_01_28.tar.gz"
CONFIG_URL = "https://raw.githubusercontent.com/opencv/opencv_extra/4.x/testdata/dnn/ssd_mobilenet_v1_coco.pbtxt"
LABELS_URL = "https://raw.githubusercontent.com/amikelive/coco-labels/master/coco-labels-2014_2017.txt"


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {url} -> {dest}")
    urllib.request.urlretrieve(url, dest)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download basic OpenCV DNN model + labels"
    )
    parser.add_argument("--dest", default="models", help="Destination folder")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    dest = (root / args.dest).resolve()
    archive = dest / "ssd_mobilenet_v1_coco_2018_01_28.tar.gz"
    graph = dest / "frozen_inference_graph.pb"
    download(CONFIG_URL, dest / "ssd_mobilenet_v1_coco.pbtxt")
    download(LABELS_URL, dest / "coco_labels.txt")
    download(MODEL_URL, archive)
    with tarfile.open(archive, "r:gz") as package:
        member = next(
            (item for item in package.getmembers() if item.name.endswith("/frozen_inference_graph.pb")),
            None,
        )
        if member is None or not member.isfile():
            raise RuntimeError("The downloaded TensorFlow archive has no frozen inference graph")
        source = package.extractfile(member)
        if source is None:
            raise RuntimeError("Unable to read frozen inference graph from archive")
        dest.mkdir(parents=True, exist_ok=True)
        with source, graph.open("wb") as output:
            output.write(source.read())
    archive.unlink(missing_ok=True)
    print("Done.")


if __name__ == "__main__":
    main()
