#!/home/iprada/bin/miniconda3/bin/python3.6
from __future__ import division


import os
import sys
from Bio.Seq import Seq
import time
from utils import *
import pandas as pd
import traceback


class realignment:
    """Class for managing the realignment and eccDNA indetification of circle-map"""

    def __init__(self, input_bam,qname_bam,sorted_bam,genome_fasta,directory,mapq_cutoff,insert_size_mapq,std_extension,
                 insert_size_sample_size,gap_open,gap_ext,n_hits,prob_cutoff,min_soft_clipped_length,overlap_frac,
                 interval_p_cut, output_name,ncores,circle_peaks,locker,split,ratio,verbose,pid,edit_distance_frac,
                 remap_splits,only_discordants):
        #I/O
        self.edit_distance_frac = edit_distance_frac
        self.ecc_dna = input_bam
        self.qname_bam = qname_bam
        self.sorted_bam = ps.AlignmentFile(sorted_bam, "rb")
        self.directory = directory
        self.genome_fa = ps.FastaFile(genome_fasta)
        self.peaks = circle_peaks.to_dataframe(names=['chrom','start','end'])

        #realignment parameters

        # probabilistic realignment options
        self.n_hits = n_hits
        self.prob_cutoff = prob_cutoff
        self.min_sc_length = min_soft_clipped_length
        self.mapq_cutoff = mapq_cutoff
        self.interval_p = interval_p_cut
        self.remap = remap_splits
        self.only_discordants = only_discordants

        # affine gap scoring options
        self.gap_open = gap_open
        self.gap_ext = gap_ext


        #insert size stimation parameters
        self.insert_size_mapq = insert_size_mapq
        self.std_extenstion = std_extension
        self.insert_sample_size = insert_size_sample_size



        #output options

        self.overlap_fraction = overlap_frac
        self.output = output_name


        #regular options
        self.cores = ncores
        self.verbose = verbose
        self.phreds_to_probs = np.vectorize(phred_to_prob)
        self.lock = locker

        #this two parameters don't work on this class. They are here for printing the parameters
        self.split = split
        self.ratio = ratio

        #for instances running on the same directoiry

        self.pid = pid





    def print_parameters(self):

        print("Running realignment\n")
        print("Probabilistic realignment parameters:\n"
              "\tAlignments to consider: %s \n"
              "\tProbability cut-off to consider as mapped: %s \n"
              "\tMinimum soft-clipped length to attemp realignment: %s \n"
              "\tMinimum bwa mem mapping quality to consider: %s \n"
              "\tGap open penalty: %s \n"
              "\tGap extension penalty: %s \n"
              % (self.n_hits, self.prob_cutoff,self.min_sc_length,self.mapq_cutoff,self.gap_open, self.gap_ext))

        print("Interval extension parameters:\n"
              "\tInsert size mapping quality cut-off: %s \n"
              "\tNumber of read to sample: %s \n"
              "\tNumber of standard deviations to extend the realignment intervals: %s \n"
              % (self.insert_size_mapq,self.insert_sample_size,self.std_extenstion))

        print("eccDNA output options: \n"
              "\tSplit read cut-off: %s \n"
              "\tCoverage ratio cut-off: %s \n" % (self.split,self.ratio))


        print("Interval processing options: \n"
              "\tMerging fraction: %s \n"
              "\tInterval probability cut-off: %s \n"
              % (self.overlap_fraction,self.interval_p))







    def realign(self):
        """Function that will iterate trough the bam file containing reads indicating eccDNA structural variants and
        will output a bed file containing the soft-clipped reads, the discordant and the coverage within the interval"""

        begin = time.time()






        # compute insert size distribution

        insert_metrics = insert_size_dist(self.insert_sample_size,self.insert_size_mapq,self.qname_bam)


        #define realignment extension interval
        extension = insert_metrics[0] + self.std_extenstion*insert_metrics[1]


        iteration = 0


        results = []
        only_discordants = []

        for index,interval in self.peaks.iterrows():
            

            if check_size_and_write(results,only_discordants,self.output,self.lock,self.directory,self.overlap_fraction,self.pid) == True:
                results = []
                only_discordants = []

            try:


    
    
                #find out the prior distribution (mate alignment positions).
                candidate_mates = get_mate_intervals(self.ecc_dna,interval,self.mapq_cutoff,self.verbose,self.only_discordants)
    
    
    
    
                #check that the output is not empty
                if len(candidate_mates) > 0:
    
    
                    # sort merge and extend
                    realignment_interval_extended = get_realignment_intervals(candidate_mates,extension,self.interval_p,
                                                                              self.verbose)
    
    
    
    
    
    
                    if realignment_interval_extended is None:
                        continue
    
    
    
                    iteration_results = []
                    iteration_discordants = []
                    disorcordants_per_it = 0
                    for index,mate_interval in realignment_interval_extended.iterrows():
    
                        iteration += 1
    
    
    
                        #sample realignment intervals
                        #fasta file fetch is 1 based that why I do +1
    
                        plus_coding_interval = self.genome_fa.fetch(mate_interval['chrom'],mate_interval['start']+1,mate_interval['end']+1).upper()
                        interval_length = len(plus_coding_interval)
                        minus_coding_interval = str(Seq(plus_coding_interval).complement())
    
                        # precompute the denominators of the error model. They will be constants for every interval
                        plus_base_freqs = background_freqs(plus_coding_interval)
                        minus_base_freqs = {'T':plus_base_freqs['A'],'A':plus_base_freqs['T'],
                                            'C':plus_base_freqs['G'],'G':plus_base_freqs['C']}
    
    
                        #note that I am getting the reads of the interval. Not the reads of the mates
                        for read in self.ecc_dna.fetch(interval['chrom'],interval['start'],interval['end'],multiple_iterators=True):
    
    
                            if is_soft_clipped(read):
    
                                if read.mapq >= self.mapq_cutoff:
    
                                    # no need to realignment
                                    if read.has_tag('SA') and self.remap != True:
    
    
                                        #check realignment from SA tag
                                        support = circle_from_SA(read, self.mapq_cutoff, mate_interval)

    
    
                                        if support is  None:
                                            continue
    
                                        else:
    
                                            if support['support'] == True:

                                                score = len(get_longest_soft_clipped_bases(read)['seq'])*  (1-phred_to_prob(int(read.get_tag('SA').split(',')[4])))
    
                                                #compute mapping positions
    
                                                read_end = rightmost_from_read(read)
    
                                                supplementary_end = rightmost_from_sa(support['leftmost'],support['cigar'])
    
    
    
                                                # I store the read name to the output, so that a read counts as 1 no matter it is SC in 2 pieces
                                                if read.reference_start < support['leftmost']:
    
                                                    iteration_results.append([interval['chrom'],read.reference_start,(supplementary_end-1),read.qname,iteration,str(round(score,2))])
    
                                                elif read.reference_start > support['leftmost']:
    
                                                    iteration_results.append(
                                                        [interval['chrom'], (support['leftmost']-1), read_end, read.qname,iteration,str(round(score,2))])
    
                                                else:
                                                    #uninformative read
                                                    continue
    

    
                                    else:
                                        #sc length
                                        sc_len = len(get_longest_soft_clipped_bases(read)['seq'])


                                        if non_colinearity(read,mate_interval) == True:

    
                                            if sc_len >= self.min_sc_length:
                                            #realignment

                                                realignment_dict = realign(read,self.n_hits,plus_coding_interval,minus_coding_interval,
                                                                           plus_base_freqs,minus_base_freqs,self.gap_open,self.gap_ext,self.verbose)


                                                if realignment_dict == None:

                                                    continue

                                                else:
                                                    #calc edit distance allowed
                                                    edits_allowed = adaptative_myers_k(sc_len, self.edit_distance_frac)
                                                    prob = realignment_probability(realignment_dict,interval_length)
                                                    if prob >= self.prob_cutoff and realignment_dict['alignments'][1][3] <= edits_allowed:

                                                        # here I have to retrieve the nucleotide mapping positions. Which should be the
                                                        # the left sampling pysam coordinate - edlib coordinates

                                                        read_end = rightmost_from_read(read)


                                                        soft_clip_start = mate_interval['start']+ int(realignment_dict['alignments'][1][0][0])

                                                        soft_clip_end = mate_interval['start'] + int(realignment_dict['alignments'][1][0][1])

                                                        score = sc_len*prob


                                                        # I store the read name to the output, so that a read counts as 1 no matter it is SC in 2 pieces
                                                        if read.reference_start < mate_interval['start'] + int(
                                                                realignment_dict['alignments'][1][0][0]):

                                                            iteration_results.append([interval['chrom'], read.reference_start, soft_clip_end+1, read.qname,iteration,str(round(score,2))])

                                                        elif read.reference_start + mate_interval['start'] + int(
                                                                realignment_dict['alignments'][1][0][0]):

                                                            iteration_results.append([interval['chrom'], soft_clip_start, read_end, read.qname,iteration,str(round(score,2))])

                                                        else:
                                                            # uninformative read
                                                            continue



                                                    else:
                                                        continue
                                        else:

                                            continue

                                else:
                                    continue
                            else:
                                #discordant reads
                                #R2F1 oriented when iterating trough R2
                                if read.is_reverse == True and read.mate_is_reverse == False:
                                    if read.is_read2:
                                        if read.reference_start < read.next_reference_start:
                                            # discordant read
                                            disorcordants_per_it +=1
                                            iteration_discordants.append([interval['chrom'],read.reference_start,read.next_reference_start + read.infer_query_length(),read.qname])
    
    
    
    
                                #R2F1 when iterating trough F1
                                elif read.is_reverse == False and read.mate_is_reverse ==  True:
                                    if read.is_read2 == False:
                                        if read.next_reference_start < read.reference_start:
                                            disorcordants_per_it +=1
                                            iteration_discordants.append([interval['chrom'], read.next_reference_start,read.reference_start+read.infer_query_length(),
                                                                          read.qname])
    
    
                    #second pass to add discordant read info
                    if len(iteration_results) > 0:
                        results = results + assign_discordants(iteration_results,iteration_discordants)

    
                    elif len(iteration_discordants) > 0:
                            discordant_bed = pd.DataFrame.from_records(iteration_discordants,columns=['chrom','start','end','read']).sort_values(['chrom','start','end'])

                            discordant_bed = discordant_bed.groupby(merge_bed(discordant_bed)).agg(
                                {'chrom': 'first', 'start': 'first', 'end': 'last', 'read': 'count'})

    
                            for index,disc_interval in discordant_bed.iterrows():
                                only_discordants.append([disc_interval['chrom'],disc_interval['start'],disc_interval['end'],disc_interval['read'],0])


            except BaseException as e:


                if self.verbose < 2:
                    traceback.print_exc(file=sys.stdout)
                    warnings.warn(
                        "Failed on interval %s due to the error %s" % (
                            str(interval), str(e)))

                else:
                    continue





        self.ecc_dna.close()

        #Write process output to disk
        output = iteration_merge(only_discordants,results,self.overlap_fraction)
        write_to_disk(output,self.output,self.lock,self.directory,self.pid)
