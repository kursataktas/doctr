# Copyright (C) 2021, Mindee.

# This program is licensed under the Apache License version 2.
# See LICENSE or go to <https://www.apache.org/licenses/LICENSE-2.0.txt> for full license details.

import os
import numpy as np
from tqdm import tqdm

os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"

import tensorflow as tf

gpu_devices = tf.config.experimental.list_physical_devices('GPU')
if any(gpu_devices):
    tf.config.experimental.set_memory_growth(gpu_devices[0], True)

from doctr.utils.metrics import LocalizationConfusion, TextMatch, OCRMetric
from doctr import datasets
from doctr.models import ocr_predictor, extract_crops


def main(args):

    predictor = ocr_predictor(args.detection, args.recognition, pretrained=True, reco_bs=args.batch_size)

    if args.img_folder and args.label_file:
        testset = datasets.OCRDataset(
            img_folder=args.img_folder,
            label_file=args.label_file,
        )
        sets = [testset]
    else:
        train_set = datasets.__dict__[args.dataset](train=True, download=True)
        val_set = datasets.__dict__[args.dataset](train=False, download=True)
        sets = [train_set, val_set]

    det_metric = LocalizationConfusion(iou_thresh=args.iou)
    reco_metric = TextMatch()
    e2e_metric = OCRMetric(iou_thresh=args.iou)

    for dataset in sets:
        for page, target in tqdm(dataset):
            # GT
            gt_boxes = target['boxes']
            gt_labels = target['labels']

            # Forward
            out = predictor(page[None, ...], training=False)
            crops = extract_crops(page, gt_boxes)
            reco_out = predictor.reco_predictor(crops, training=False)
            reco_words, _ = zip(*reco_out)

            # Unpack preds
            pred_boxes = []
            pred_labels = []
            for page in out.pages:
                h, w = page.dimensions
                for block in page.blocks:
                    for line in block.lines:
                        for word in line.words:
                            (a, b), (c, d) = word.geometry
                            if gt_boxes.dtype == int:
                                pred_boxes.append([int(a * w), int(b * h), int(c * w), int(d * h)])
                            else:
                                pred_boxes.append([a, b, c, d])
                            pred_labels.append(word.value)

            # Update the metric
            det_metric.update(gt_boxes, np.asarray(pred_boxes))
            reco_metric.update(gt_labels, reco_words)
            e2e_metric.update(gt_boxes, np.asarray(pred_boxes), gt_labels, pred_labels)

    # Unpack aggregated metrics
    print(f"Model Evaluation (model= {args.detection} + {args.recognition}, "
          f"dataset={'OCRDataset' if args.img_folder else args.dataset})")
    recall, precision, mean_iou = det_metric.summary()
    print(f"Text Detection - Recall: {recall:.2%}, Precision: {precision:.2%}, Mean IoU: {mean_iou:.2%}")
    acc = reco_metric.summary()
    print(f"Text Recognition - Accuracy: {acc['raw']:.2%} (unicase: {acc['unicase']:.2%})")
    recall, precision, mean_iou = e2e_metric.summary()
    print(f"OCR - Recall: {recall['raw']:.2%} (unicase: {recall['unicase']:.2%}), "
          f"Precision: {precision['raw']:.2%} (unicase: {precision['unicase']:.2%}), Mean IoU: {mean_iou:.2%}")


def parse_args():
    import argparse
    parser = argparse.ArgumentParser(description='DocTR end-to-end evaluation',
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument('detection', type=str, help='Text detection model to use for analysis')
    parser.add_argument('recognition', type=str, help='Text recognition model to use for analysis')
    parser.add_argument('--iou', type=float, default=0.5, help='IoU threshold to match a pair of boxes')
    parser.add_argument('--dataset', type=str, default='FUNSD', help='choose a dataset: FUNSD, CORD')
    parser.add_argument('--img_folder', type=str, default=None, help='Only for local sets, path to images')
    parser.add_argument('--label_file', type=str, default=None, help='Only for local sets, path to labels')
    parser.add_argument('-b', '--batch_size', type=int, default=32, help='batch size for recognition')
    args = parser.parse_args()

    return args


if __name__ == "__main__":
    args = parse_args()
    main(args)