#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
parses JCVI software NUCMER (http://mummer.sourceforge.net/manual/)
output - mostly as *.coords file.
"""
import os.path as op
import sys

from itertools import groupby
from math import exp

from ..apps.base import (
    ActionDispatcher,
    OptionParser,
    get_abs_path,
    logger,
    need_update,
    sh,
)
from ..assembly.base import calculate_A50

from .base import LineFile, must_open
from .blast import AlignStats


Overlap_types = ("none", "a ~ b", "b ~ a", "a in b", "b in a")


class CoordsLine(object):
    """
    The coords line looks like (in one line):
    2953     4450  |      525     2023  |     1498     1499  |    98.07  |
    8046     2023  |    18.62    74.10  | AC182814.30   contig_100476

    the coords file needs to be generated by `show-coords -rcl`
    """

    def __init__(self, row):

        row = row.replace(" | ", "")
        atoms = row.split()
        assert len(atoms) in (13, 17), "expecting 13 or 17 columns"

        self.start1 = int(atoms[0])
        self.end1 = int(atoms[1])

        self.start2 = int(atoms[2])
        self.end2 = int(atoms[3])

        if self.start2 > self.end2:
            self.start2, self.end2 = self.end2, self.start2
            self.orientation = "-"
        else:
            self.orientation = "+"

        self.len1 = int(atoms[4])
        self.len2 = int(atoms[5])

        self.identity = float(atoms[6])

        self.reflen = int(atoms[7])
        self.querylen = int(atoms[8])

        self.refcov = float(atoms[9]) / 100.0
        self.querycov = float(atoms[10]) / 100.0

        self.ref = atoms[11]
        self.query = atoms[12]

        # this is taken from CoGeBlast:
        # the coverage of the hit muliplied by percent seq identity
        # range from 0-100
        self.quality = self.identity * self.querycov
        self.score = int(self.identity * self.len1 / 100)

    def __str__(self):
        slots = "ref start1 end1 reflen " + "query start2 end2 querylen orientation"
        return "\t".join(
            str(x) for x in [getattr(self, attr) for attr in slots.split()]
        )

    def bedline(self, pctid=False):
        score = self.identity if pctid else self.score
        return "\t".join(
            str(x)
            for x in (
                self.ref,
                self.start1 - 1,
                self.end1,
                self.query,
                score,
                self.orientation,
            )
        )

    def qbedline(self, pctid=False):
        score = self.identity if pctid else self.score
        return "\t".join(
            str(x)
            for x in (
                self.query,
                self.start2 - 1,
                self.end2,
                self.ref,
                score,
                self.orientation,
            )
        )

    @property
    def blastline(self):
        hitlen = max(self.len1, self.len2)
        score = self.score
        mismatch = int(self.len1 * (1 - self.identity / 100))
        log_prob = -score * 0.693147181
        evalue = 3.0e9 * exp(log_prob)
        evalue = "{0:.1g}".format(evalue)
        return "\t".join(
            str(x)
            for x in (
                self.query,
                self.ref,
                self.identity,
                hitlen,
                mismatch,
                0,
                self.start2,
                self.end2,
                self.start1,
                self.end1,
                evalue,
                score,
            )
        )

    def overlap(self, max_hang=100):
        r"""
        Determine the type of overlap given query, ref alignment coordinates
        Consider the following alignment between sequence a and b:

        aLhang \              / aRhang
                \------------/
                /------------\
        bLhang /              \ bRhang

        Terminal overlap: a before b, b before a
        Contain overlap: a in b, b in a
        """
        aL, aR = 1, self.reflen
        bL, bR = 1, self.querylen
        aLhang, aRhang = self.start1 - aL, aR - self.end1
        bLhang, bRhang = self.start2 - bL, bR - self.end2
        if self.orientation == "-":
            bLhang, bRhang = bRhang, bLhang

        s1 = aLhang + bRhang
        s2 = aRhang + bLhang
        s3 = aLhang + aRhang
        s4 = bLhang + bRhang

        # Dovetail (terminal) overlap
        if s1 < max_hang:
            type = 2  # b ~ a
        elif s2 < max_hang:
            type = 1  # a ~ b
        # Containment overlap
        elif s3 < max_hang:
            type = 3  # a in b
        elif s4 < max_hang:
            type = 4  # b in a
        else:
            type = 0

        return type


class Coords(LineFile):
    """
    when parsing the .coords file, first skip first 5 lines
    [S1] [E1] | [S2] [E2] | [LEN 1] [LEN 2] | [% IDY] | [TAGS]

    then each row would be composed as this
    """

    def __init__(self, filename, sorted=False, header=False):

        if filename.endswith(".delta"):
            coordsfile = filename.rsplit(".", 1)[0] + ".coords"
            if need_update(filename, coordsfile):
                fromdelta([filename])
            filename = coordsfile

        super().__init__(filename)

        fp = open(filename)
        if header:
            self.cmd = next(fp)

        for row in fp:
            try:
                self.append(CoordsLine(row))
            except AssertionError:
                pass

        if sorted:
            self.ref_sort()

    def ref_sort(self):
        # sort by reference positions
        self.sort(key=lambda x: (x.ref, x.start1))

    def quality_sort(self):
        # sort descending with score = identity * coverage
        self.sort(key=lambda x: (x.query, -x.quality))

    @property
    def hits(self):
        """
        returns a dict with query => blastline
        """
        self.quality_sort()

        hits = dict(
            (query, list(blines))
            for (query, blines) in groupby(self, lambda x: x.query)
        )

        self.ref_sort()

        return hits

    @property
    def best_hits(self):
        """
        returns a dict with query => best mapped position
        """
        self.quality_sort()

        best_hits = dict(
            (query, next(blines))
            for (query, blines) in groupby(self, lambda x: x.query)
        )

        self.ref_sort()

        return best_hits


def get_stats(coordsfile):

    from jcvi.utils.range import range_union

    logger.debug("Report stats on `%s`", coordsfile)
    coords = Coords(coordsfile)
    ref_ivs = []
    qry_ivs = []
    identicals = 0
    alignlen = 0
    alignlens = []

    for c in coords:

        qstart, qstop = c.start2, c.end2
        if qstart > qstop:
            qstart, qstop = qstop, qstart
        qry_ivs.append((c.query, qstart, qstop))

        sstart, sstop = c.start1, c.end1
        if sstart > sstop:
            sstart, sstop = sstop, sstart
        ref_ivs.append((c.ref, sstart, sstop))

        alen = sstop - sstart
        alignlen += alen
        identicals += c.identity / 100.0 * alen
        alignlens.append(alen)

    qrycovered = range_union(qry_ivs)
    refcovered = range_union(ref_ivs)
    _, AL50, _ = calculate_A50(alignlens)
    filename = op.basename(coordsfile)
    alignstats = AlignStats(
        filename, qrycovered, refcovered, None, None, identicals, AL50
    )

    return alignstats


def main():

    actions = (
        ("annotate", "annotate overlap types in coordsfile"),
        ("blast", "convert to blast tabular output"),
        ("filter", "filter based on id% and cov%, write a new coords file"),
        ("fromdelta", "convert deltafile to coordsfile"),
        ("merge", "merge deltafiles"),
        ("sort", "sort coords file based on query or subject"),
        ("summary", "provide summary on id% and cov%"),
    )
    p = ActionDispatcher(actions)
    p.dispatch(globals())


def merge(args):
    """
    %prog merge ref.fasta query.fasta *.delta

    Merge delta files into a single delta.
    """
    p = OptionParser(merge.__doc__)
    p.set_outfile(outfile="merged_results.delta")
    opts, args = p.parse_args(args)

    if len(args) < 3:
        sys.exit(not p.print_help())

    ref, query = args[:2]
    deltafiles = args[2:]
    outfile = opts.outfile

    ref = get_abs_path(ref)
    query = get_abs_path(query)
    fw = must_open(outfile, "w")
    print(" ".join((ref, query)), file=fw)
    print("NUCMER", file=fw)
    fw.close()

    for d in deltafiles:
        cmd = "awk 'NR > 2 {{print $0}}' {0}".format(d)
        sh(cmd, outfile=outfile, append=True)


def blast(args):
    """
    %prog blast <deltafile|coordsfile>

    Covert delta or coordsfile to BLAST tabular output.
    """
    p = OptionParser(blast.__doc__)
    opts, args = p.parse_args(args)

    if len(args) != 1:
        sys.exit(not p.print_help())

    (deltafile,) = args
    blastfile = deltafile.rsplit(".", 1)[0] + ".blast"

    if need_update(deltafile, blastfile):
        coords = Coords(deltafile)
        fw = open(blastfile, "w")
        for c in coords:
            print(c.blastline, file=fw)


def fromdelta(args):
    """
    %prog fromdelta deltafile

    Convert deltafile to coordsfile.
    """
    p = OptionParser(fromdelta.__doc__)
    opts, args = p.parse_args(args)

    if len(args) != 1:
        sys.exit(not p.print_help())

    (deltafile,) = args
    coordsfile = deltafile.rsplit(".", 1)[0] + ".coords"
    cmd = "show-coords -rclH {0}".format(deltafile)
    sh(cmd, outfile=coordsfile)

    return coordsfile


def sort(args):
    """
    %prog sort coordsfile

    Sort coordsfile based on query or ref.
    """
    import jcvi.formats.blast

    return jcvi.formats.blast.sort(args + ["--coords"])


def coverage(args):
    """
    %prog coverage coordsfile

    Report the coverage per query record, useful to see which query matches
    reference.  The coords file MUST be filtered with supermap::

    jcvi.algorithms.supermap --filter query
    """
    p = OptionParser(coverage.__doc__)
    p.add_argument(
        "-c",
        dest="cutoff",
        default=0.5,
        type=float,
        help="only report query with coverage greater than",
    )

    opts, args = p.parse_args(args)

    if len(args) != 1:
        sys.exit(not p.print_help())

    (coordsfile,) = args
    fp = open(coordsfile)

    coords = []
    for row in fp:
        try:
            c = CoordsLine(row)
        except AssertionError:
            continue
        coords.append(c)

    coords.sort(key=lambda x: x.query)

    coverages = []
    for query, lines in groupby(coords, key=lambda x: x.query):
        cumulative_cutoff = sum(x.querycov for x in lines)
        coverages.append((query, cumulative_cutoff))

    coverages.sort(key=lambda x: (-x[1], x[0]))
    for query, cumulative_cutoff in coverages:
        if cumulative_cutoff < opts.cutoff:
            break
        print("{0}\t{1:.2f}".format(query, cumulative_cutoff))


def annotate(args):
    """
    %prog annotate coordsfile

    Annotate coordsfile to append an additional column, with the following
    overlaps: {0}.
    """
    p = OptionParser(annotate.__doc__.format(", ".join(Overlap_types)))
    p.add_argument(
        "--maxhang",
        default=100,
        type=int,
        help="Max hang to call dovetail overlap",
    )
    p.add_argument(
        "--all",
        default=False,
        action="store_true",
        help="Output all lines [default: terminal/containment]",
    )

    opts, args = p.parse_args(args)

    if len(args) != 1:
        sys.exit(not p.print_help())

    (coordsfile,) = args
    fp = open(coordsfile)

    for row in fp:
        try:
            c = CoordsLine(row)
        except AssertionError:
            continue

        ov = c.overlap(opts.maxhang)
        if not opts.all and ov == 0:
            continue

        print("{0}\t{1}".format(row.strip(), Overlap_types[ov]))


def summary(args):
    """
    %prog summary coordsfile

    provide summary on id% and cov%, for both query and reference
    """

    p = OptionParser(summary.__doc__)
    p.add_argument(
        "-s",
        dest="single",
        default=False,
        action="store_true",
        help="provide stats per reference seq",
    )

    opts, args = p.parse_args(args)

    if len(args) != 1:
        sys.exit(p.print_help())

    (coordsfile,) = args
    alignstats = get_stats(coordsfile)
    alignstats.print_stats()


def filter(args):
    """
    %prog filter <deltafile|coordsfile>

    Produce a new delta/coords file and filter based on id% or cov%.
    Use `delta-filter` for .delta file.
    """
    p = OptionParser(filter.__doc__)
    p.set_align(pctid=0, hitlen=0)
    p.add_argument(
        "--overlap",
        default=False,
        action="store_true",
        help="Print overlap status (e.g. terminal, contained)",
    )

    opts, args = p.parse_args(args)
    if len(args) != 1:
        sys.exit(not p.print_help())

    pctid = opts.pctid
    hitlen = opts.hitlen

    (filename,) = args
    if pctid == 0 and hitlen == 0:
        return filename

    pf, suffix = filename.rsplit(".", 1)
    outfile = "".join((pf, ".P{0}L{1}.".format(int(pctid), int(hitlen)), suffix))
    if not need_update(filename, outfile):
        return outfile

    if suffix == "delta":
        cmd = "delta-filter -i {0} -l {1} {2}".format(pctid, hitlen, filename)
        sh(cmd, outfile=outfile)
        return outfile

    fp = open(filename)
    fw = must_open(outfile, "w")
    for row in fp:
        try:
            c = CoordsLine(row)
        except AssertionError:
            continue

        if c.identity < pctid:
            continue
        if c.len2 < hitlen:
            continue
        if opts.overlap and not c.overlap:
            continue

        outrow = row.rstrip()
        if opts.overlap:
            ov = Overlap_types[c.overlap]
            outrow += "\t" + ov
        print(outrow, file=fw)

    return outfile


def bed(args):
    """
    %prog bed coordsfile

    will produce a bed list of mapped position and orientation (needs to
    be beyond quality cutoff, say 50) in bed format
    """
    p = OptionParser(bed.__doc__)
    p.add_argument(
        "--query",
        default=False,
        action="store_true",
        help="print out query intervals rather than ref",
    )
    p.add_argument(
        "--pctid",
        default=False,
        action="store_true",
        help="use pctid in score",
    )
    p.add_argument(
        "--cutoff",
        dest="cutoff",
        default=0,
        type=float,
        help="get all the alignments with quality above threshold",
    )

    opts, args = p.parse_args(args)
    if len(args) != 1:
        sys.exit(p.print_help())

    (coordsfile,) = args
    query = opts.query
    pctid = opts.pctid
    quality_cutoff = opts.cutoff

    coords = Coords(coordsfile)

    for c in coords:
        if c.quality < quality_cutoff:
            continue
        line = c.qbedline(pctid=pctid) if query else c.bedline(pctid=pctid)
        print(line)


if __name__ == "__main__":
    main()
