#!/usr/bin/env python
# -*- coding: UTF-8 -*-

import os.path as op
import numpy as np

from jcvi.formats.base import LineFile
from jcvi.apps.base import sh


class Sizes (LineFile):
    """
    Two-column .sizes file, often generated by `faSize -detailed`
    contigID size
    """
    def __init__(self, filename):
        assert op.exists(filename), "File `{0}` not found".format(filename)

        # filename can be both .sizes file or FASTA formatted file
        sizesname = filename

        if not filename.endswith(".sizes"):
            sizesname = filename + ".sizes"
            if not op.exists(sizesname):
                cmd = "faSize -detailed {0} ".format(filename)
                sh(cmd, outfile=sizesname)
            filename = sizesname

        assert filename.endswith(".sizes")

        super(Sizes, self).__init__(filename)
        self.fp = open(filename)

        # get sizes for individual contigs, both in list and dict
        # this is to preserve the input order in the sizes file
        sizes = list(self.iter_sizes())
        self.sizes_mapping = dict(sizes)
        
        # get cumulative sizes, both in list and dict
        ctgs, sizes = zip(*sizes)
        self.sizes = sizes
        cumsizes = np.cumsum([0] + list(sizes)[:-1])
        self.ctgs = ctgs
        self.cumsizes = cumsizes
        self.cumsizes_mapping = dict(zip(ctgs, cumsizes))

    def __len__(self):
        return len(self.sizes)

    def get_size(self, ctg):
        return self.sizes_mapping[ctg]

    def get_cumsize(self, ctg):
        return self.cumsizes_mapping[ctg]

    @property
    def totalsize(self):
        return sum(self.sizes)

    def iter_sizes(self):
        self.fp.seek(0)
        for row in self.fp:
            ctg, size = row.split()[:2]
            yield ctg, int(size)

    def get_position(self, ctg, pos):
        if ctg not in self.cumsizes_mapping: return None
        return self.cumsizes_mapping[ctg] + pos

    def get_breaks(self):
        for i in xrange(1, len(self)):
            yield self.ctgs[i], self.cumsizes[i-1], self.cumsizes[i]



