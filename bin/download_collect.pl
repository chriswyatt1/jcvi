#!/usr/bin/perl
#Bed_to_histogram.pl
use warnings;
use strict;

die "Needs the input accension id and sample id\n" if (@ARGV!=2); 

my $accension_id=$ARGV[0];
my $sample_id=$ARGV[1];

#Check which type of genome we have, then collect the genome into a single file
#my @files=`ls ncbi_dataset/data/$accension_id/chr*.fna`;

#print "@files\n";

#my @src=`ls ncbi_dataset/data/$accension_id`;


my @txtfiles = glob "ncbi_dataset/data/$accension_id\/*";
my $chr_split=0;
my $chromosome=0;
my $chromosome_alt=0;
foreach my $txtfile (@txtfiles){
    print "$txtfile\n";
    if($txtfile=~ m/chr(.*?).fna/){
        $chr_split=1;
    }
    if($txtfile=~ m/scale_assembly_genomic.fna/){
        $chromosome=$txtfile;
    }
    if($txtfile=~m/ncbi_dataset\/data\/$accension_id\/$accension_id/){
        if ($txtfile=~m/_genomic.fna$/){
            $chromosome_alt=$txtfile;
        }
    }
}

#print "$chr_split\n";
print "$chromosome\n";

if ($chr_split) {
    `cat ncbi_dataset/data/$accension_id\/chr*.fna > $sample_id\.genome.fna`;
    if (`ls ncbi_dataset/data/$accension_id\/unplaced.scaf.fna`){
        `cat ncbi_dataset/data/$accension_id\/unplaced.scaf.fna >> $sample_id\.genome.fna`;
    }
}
elsif ($chromosome){
    my $file = `ls ncbi_dataset/data/$accension_id\/*scale_assembly_genomic.fna`;
    `cp $chromosome $sample_id\.genome.fna`;
}
elsif ($chromosome_alt){
    my $file = `ls ncbi_dataset/data/$accension_id\*genomic.fna`;
    `cp $chromosome_alt $sample_id\.genome.fna`;
}
else{
    print "ncbi_dataset/data/$accension_id\/*scale_assembly_genomic.fna\n";
    die "Could not recognise genome file for species: $sample_id\n";
}
        

#Add the gff file to a new named file to go forwards
`cat ncbi_dataset/data/$accension_id\/genomic.gff > $sample_id\.genomic.gff`
