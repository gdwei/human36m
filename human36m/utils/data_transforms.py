from __future__ import division
import torch
import math
import random
from PIL import Image, ImageOps
import numpy as np
import numbers
import types
import collections

class Compose(object):
    """Composes several transforms together.
    Args:
        transforms (List[Transform]): list of transforms to compose.
    Example:
        >>> transforms.Compose([
        >>>     transforms.CenterCrop(10),
        >>>     transforms.ToTensor(),
        >>> ])
    """

    def __init__(self, transforms):
        self.transforms = transforms

    def __call__(self, img, target):
        for t in self.transforms:
            img, target = t(img, target)
        return img, target

class CropToTarget(object):
    """Crops the given image using a bounding box defined by the target."""

    def __init__(self, padding=0):
        self.padding = padding

    def __call__(self, img, target):
        # Calculate the bounding box as defined by the target
        max_coords = np.max(target, axis=0)
        min_coords = np.min(target, axis=0)
        w, h = img.size

        # add padding
        if not ((min_coords[0] - self.padding) < 0 or
            (min_coords[1] - self.padding) < 0 or
            (max_coords[0] + self.padding) > w or
            (max_coords[1] + self.padding) > h):
            min_coords -= self.padding
            max_coords += self.padding

        if w == max_coords[0] and h == max_coords[1]:
            return img, target

        # Crop img
        img = img.crop((min_coords[0], min_coords[1], max_coords[0],
            max_coords[1]))

        # Crop target
        target[:, 0] -= min_coords[0]
        target[:, 1] -= min_coords[1]
        target[target < 0] = 0
        target[:, 0] = np.where(target[:, 0] > max_coords[0], 0, target[:, 0])
        target[:, 1] = np.where(target[:, 1] > max_coords[1], 0, target[:, 1])

        return img, target

class Scale(object):
    """Scales the given image and target
    TODO: Need to handle non-square cases properly for targets
    """

    def __init__(self, size, interpolation=Image.BILINEAR):
        assert isinstance(size, int) or \
            (isinstance(size, collections.Iterable) and len(size) == 2)

        self.size = size
        self.interpolation = interpolation

    def __call__(self, img, target):
        if isinstance(self.size, int):
            w, h = img.size
            if (w <= h and w == self.size) or (h <= w and h == self.size):
                return img, target
            if w < h:
                ow = self.size
                oh = int(self.size * h / w)
                img = img.resize((ow, oh), self.interpolation)
                target[:, 0] *= ow
                target[:, 1] *= oh
                return img, target
            else:
                oh = self.size
                ow = int(self.size * w / h)
                target[:, 0] *= ow
                target[:, 1] *= oh
                img = img.resize((ow, oh), self.interpolation)
                return img, target
        else:
            w, h = img.size
            img = img.resize(self.size, self.interpolation)
            target[:, 0] *= (self.size[0] / w)
            target[:, 1] *= (self.size[1] / h)
            return img, target

class RandomCrop(object):
    """Crops the given image and target"""

    def __init__(self, size, padding=0):
        if isinstance(size, numbers.Number):
            self.size = (int(size), int(size))
        else:
            self.size = size
        self.padding = padding

    def __call__(self, img, target):
        if self.padding > 0:
            img = ImageOps.expand(img, border=self.padding, fill=0)

        w, h = img.size
        th, tw = self.size
        if w == th and h == th:
            return img, target

        x1 = random.randint(0, w - tw)
        y1 = random.randint(0, h - th)

        # Crop img
        img = img.crop((x1, y1, x1 + tw, y1 + th))

        # Crop target
        target[:, 0] -= x1
        target[:, 1] -= y1
        target[target < 0] = 0
        target[:, 0] = np.where(target[:, 0] > x1 + tw, 0, target[:, 0])
        target[:, 1] = np.where(target[:, 1] > y1 + th, 0, target[:, 1])

        return img, target

class RandomHorizontalFlip(object):
    """Randomly horizontally flips the given PIL.Image with a probability of
    0.5. The target is flipped as well.
    """

    def __call__(self, img, target):
        if random.random() < 0.5:
            w, h = img.size
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
            target[:, 0] = w - target[:, 0]
            return img, target

        return img, target

class Normalize(object):
    """Given mean: (R, G, B) and std: (R, G, B),
    will normalize each channel of the torch.*Tensor, i.e.
    channel = (channel - mean) / std
    """

    def __init__(self, mean, std):
        self.mean = mean
        self.std = std

    def __call__(self, tensor, target):
        # TODO: make efficient
        for t, m, s in zip(tensor, self.mean, self.std):
            t.sub_(m).div_(s)
        return tensor, target

class ToTensor(object):
    """Converts a PIL.Image or numpy.ndarray (H x W x C) in the range
    [0, 255] to a torch.FloatTensor of shape (C x H x W) in the range [0.0, 1.0].
    """

    def __call__(self, pic, target):
        if isinstance(pic, np.ndarray):
            h = pic.shape[0]
            w = pic.shape[1]
            target[:, 0] /= w
            target[:, 1] /= h

            # handle numpy array
            img = torch.from_numpy(pic.transpose((2, 0, 1)))
            # backard compability
            return img.float().div(255), target
        # handle PIL Image
        if pic.mode == 'I':
            img = torch.from_numpy(np.array(pic, np.int32, copy=False))
        elif pic.mode == 'I;16':
            img = torch.from_numpy(np.array(pic, np.int16, copy=False))
        else:
            img = torch.ByteTensor(torch.ByteStorage.from_buffer(pic.tobytes()))
        # PIL image mode: 1, L, P, I, F, RGB, YCbCr, RGBA, CMYK
        if pic.mode == 'YCbCr':
            nchannel = 3
        elif pic.mode == 'I;16':
            nchannel = 1
        else:
            nchannel = len(pic.mode)
        img = img.view(pic.size[1], pic.size[0], nchannel)
        # put it from HWC to CHW format
        # yikes, this transpose takes 80% of the loading time/CPU
        img = img.transpose(0, 1).transpose(0, 2).contiguous()
        h = img.size(1)
        w = img.size(2)
        target[:, 0] /= w
        target[:, 1] /= h

        if isinstance(img, torch.ByteTensor):
            return img.float().div(255), target
        else:
            return img, target

class ToPILImage(object):
    """Converts a torch.*Tensor of shape C x H x W or a numpy ndarray of shape
    H x W x C to a PIL.Image while preserving value range.
    """

    def __call__(self, pic, target):
        npimg = pic
        mode = None
        if isinstance(pic, torch.FloatTensor):
            pic = pic.mul(255).byte()
        if torch.is_tensor(pic):
            npimg = np.transpose(pic.numpy(), (1, 2, 0))
        assert isinstance(npimg, np.ndarray), 'pic should be Tensor or ndarray'
        if npimg.shape[2] == 1:
            npimg = npimg[:, :, 0]

            if npimg.dtype == np.uint8:
                mode = 'L'
            if npimg.dtype == np.int16:
                mode = 'I;16'
            if npimg.dtype == np.int32:
                mode = 'I'
            elif npimg.dtype == np.float32:
                mode = 'F'
        else:
            if npimg.dtype == np.uint8:
                mode = 'RGB'
        assert mode is not None, '{} is not supported'.format(npimg.dtype)
        return Image.fromarray(npimg, mode=mode), target
