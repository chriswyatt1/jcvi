process CHROMOPAINT {
    label 'chromo'
    tag "$anchors"
    publishDir "$params.outdir/Chromosome_plots" , mode: "copy"
    container = 'chriswyatt/jcvi'
    errorStrategy = 'ignore'
             
    input:

	path (hex)
        each (anchors)
        path ('*')
    
    output:
        
        path("*.pdf"), emit: pdf

    script:
    """
        echo '${anchors}' | rev | cut -d'/' -f 1 | rev > Name

        A="\$(cut -d'.' -f1 Name)"
        B="\$(cut -d'.' -f2 Name)"
        anchor.pl \$A.bed \$B.bed ${anchors} 
        python -m jcvi.graphics.chromosome Chromopaint.txt colour.idmap
        mv Chromopaint.pdf "\$A.\$B.chromo.pdf"
    """
}
