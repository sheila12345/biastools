import argparse
import re
from indelpost import Variant, VariantAlignment
import pickle
import os.path
from os import path
import pysam
import numpy as np


def fetch_alt_seqs(
        var:pysam.VariantRecord,
        ref:str
        )-> list:
    """
    Inputs: 
        - variant
        - reference sequence
    Ouput:
        - list of alternatives sequences
    """
    list_alt_seqs = []
    for idx, alt in enumerate(var.alts):
        var_seq = ref[:var.start] + alt + ref[var.stop:]
        list_alt_seqs.append(var_seq)
    return list_alt_seqs


def parse_MD(md_tag):
    list_string = re.split('(\d+)', md_tag)
    list_chunk = []
    for ele in list_string:
        if ele.isdigit():
            list_chunk.append(('M', int(ele)))
        elif ele == "":
            continue
        elif ele[0] == '^':
            list_chunk.append(('D', ele[1:]))
        else:
            list_chunk.append(('m', ele))
    return list_chunk



def map_read_to_ref(
    read_start   :int,
    read_end     :int,
    cigar_tuples :list
    ) -> dict:
    """
    return the mapping of ref->read position
    """
    dict_read_map = {}
    ref_curser  = read_start
    read_curser = 0
    for pair_info in cigar_tuples:
        code, runs = pair_info
        if code == 0 or code == 7 or code == 8: # M or = or X
            for pos in range(ref_curser, ref_curser + runs):
                dict_read_map[pos] = read_curser
                read_curser += 1
            ref_curser += runs
        elif code == 1: # I
            dict_read_map[ref_curser] = read_curser
            ref_curser  += 1
            read_curser += runs
        elif code == 2: # D
            for pos in range(ref_curser, ref_curser + runs):
                dict_read_map[pos] = read_curser
            read_curser += 1
            ref_curser += runs
        elif code == 4 or code == 5: # S or H, pysam already parsed
            pass
        else:
            print ("ERROR: unexpected cigar code in sequence", query_name)
    return dict_read_map


def match_hap(
        var_start   :int,
        read_map    :dict,
        seq_read    :str,
        seq_hap     :str,
        padding     :int
        ) -> bool:
    """
    Adjust and compare the two sequences
    """
    r_start = read_map[var_start]
    l_bound = r_start - padding
    r_bound = l_bound + len(seq_hap)
    if l_bound < 0:
        seq_hap = seq_hap[-l_bound:]
        l_bound = 0
    if r_bound > len(seq_read):
        seq_hap = seq_hap[:len(seq_read)-r_bound]
        r_bound = len(seq_read)
    if seq_read[l_bound:r_bound] == seq_hap:
        return True
    else:
        return False


"""
functions above are obsolete
"""


def output_report(
        f_vcf                   :pysam.VariantFile,
        dict_ref_bias           :dict,
        dict_set_conflict_vars  :dict,
        fn_output               :str
        ) -> None:
    """
    Output the reference bias report to three different files:
        - f_all: containing all the variants
        - f_gap: contains only insertions and deletions
        - f_SNP: contains only SNPs
    """
    f_all = open(fn_output, 'w')
    f_gap = open(fn_output + '.gap', 'w')
    f_SNP = open(fn_output + '.SNP', 'w')
    f_all.write("CHR\tHET_SITE\tREFERENCE_BIAS\tREF_COUNT\tALT_COUNT\tBOTH_COUNT\tNEITHER_COUNT\tNUM_READS\tSUM_MAPQ\tREAD_DISTRIBUTION\tGAP\n")
    f_gap.write("CHR\tHET_SITE\tREFERENCE_BIAS\tREF_COUNT\tALT_COUNT\tBOTH_COUNT\tNEITHER_COUNT\tNUM_READS\tSUM_MAPQ\tREAD_DISTRIBUTION\n")
    f_SNP.write("CHR\tHET_SITE\tREFERENCE_BIAS\tREF_COUNT\tALT_COUNT\tBOTH_COUNT\tNEITHER_COUNT\tNUM_READS\tSUM_MAPQ\tREAD_DISTRIBUTION\n")
    for var in f_vcf:
        ref_name = var.contig
        hap = var.samples[0]['GT']
        # Filtering all the homozygous alleles or the alleles without reference
        if (hap[0] != 0 and hap[1] != 0) or (hap[0] == 0 and hap[1] == 0):
            continue
        if hap[0] == 0:
            idx_ref, idx_alt = 0, 1
        else:
            idx_ref, idx_alt = 1, 0
        # Filtering the conflict vars
        if var.start in dict_set_conflict_vars[ref_name]:
            continue
        n_read = dict_ref_bias[ref_name][var.start]['n_read']
        n_var  = dict_ref_bias[ref_name][var.start]['n_var']
        map_q  = dict_ref_bias[ref_name][var.start]['map_q']
        output_string = (ref_name + '\t' + str(var.start+1) + '\t')
        # n_var[0,1,2,3] = hap0, hap1, both, others
        if sum(n_var[:3]) == 0:
            output_string += ("N/A")
        else:
            output_string += (format((n_var[idx_ref]+0.5*n_var[2]) / float(sum(n_var[:3])), '.8f'))
        output_string += ("\t" + str(n_var[idx_ref]) + "\t" + str(n_var[idx_alt]) + "\t" + str(n_var[2]) +"\t" + str(n_var[3]) + "\t" + str(sum(n_read)) + "\t" + str(sum(map_q)) + "\t")
        if sum(n_read) == 0:
            output_string += ("N/A")
        else:
            output_string += (format(n_read[idx_ref] / float(sum(n_read)), '.8f'))
        
        if len(var.ref) ==  len(var.alts[ hap[idx_alt] - 1]): # length of ref is equal to length of 
            f_all.write(output_string + '\t' + '\n')
            f_SNP.write(output_string + '\n')
        else:
            f_all.write(output_string + '\t' + '.\n')
            f_gap.write(output_string + '\n')
    
    f_all.close()
    f_gap.close()
    f_SNP.close()


def hap_inside(
        seq_read    :str,
        seq_hap     :str,
        padding     :int
        ) -> bool:
    """
    Finding if the haplotype is in the read
    Also considering the boundary condition
    One padding side can be omitted
    """
    if seq_hap in seq_read:
        return True
    else:
        len_hap = len(seq_hap)
        for idx in range(1,padding):
            # checking read left side
            if seq_hap[idx:] == seq_read[:len_hap - idx]:
                return True
            # checking read right side
            if seq_hap[:-idx] == seq_read[idx - len_hap:]:
                return True
    return False


def return_locate_cigar(
        read_start  :int,
        target_pos  :int,
        cigar_tuples:tuple
        ) -> int:
    """
    return the cigar value of a location
    according to the CIGAR string
    """
    ref_curser  = read_start -1
    read_curser = 0
    for pair_info in cigar_tuples:
        code, runs = pair_info
        if code == 0 or code == 7 or code == 8: # M or = or X
            ref_curser += runs
            if ref_curser > target_pos:
                return 0
            else:
                read_curser += runs
        elif code == 1: # I
            ref_curser  += 1
            if ref_curser > target_pos:
                return -runs
            else:
                read_curser += runs
        elif code == 2: # D
            ref_curser += runs
            if ref_curser > target_pos:
                return runs
            else:
                read_curser += 1
        elif code == 4 or code == 5: # S or H, pysam already parsed
            pass
        else:
            print ("ERROR: unexpected cigar code in sequence")
    return 0


def locate_by_cigar(
        read_start  :int,
        target_pos  :int,
        cigar_tuples:tuple
        ) -> int:
    """
    return the location of a specific reference position in the read
    according to the CIGAR string
    """
    ref_curser  = read_start
    read_curser = 0
    for pair_info in cigar_tuples:
        code, runs = pair_info
        if code == 0 or code == 7 or code == 8: # M or = or X
            ref_curser += runs
            if ref_curser > target_pos:
                return read_curser + (runs - ref_curser + target_pos)
            else:
                read_curser += runs
        elif code == 1: # I
            #ref_curser  += 1
            if ref_curser > target_pos:
                return read_curser
            else:
                read_curser += runs
        elif code == 2: # D
            ref_curser += runs
            if ref_curser > target_pos:
                return read_curser
            #else:
            #    read_curser += 1
        elif code == 4 or code == 5: # S or H, pysam already parsed
            pass
        else:
            print ("ERROR: unexpected cigar code in sequence")
    return read_curser


def match_to_hap(
        read_start  :int,
        var_start   :int,
        seq_read    :str,
        seq_hap     :str,
        cigar_tuples:tuple,
        padding     :int
        ) -> bool:
    """
    1. Find the matching point of the variant on the read
    2. Extend the padding on the read
    3. compare the read to haplotype sequences
    """
    if read_start > var_start:
        return False
    
    # locating the variant site on the read
    r_start = locate_by_cigar(
            read_start=read_start,
            target_pos=var_start,
            cigar_tuples=cigar_tuples
            )
    
    # matching
    l_bound = r_start - padding
    r_bound = l_bound + len(seq_hap)
    if l_bound < 0:
        seq_hap = seq_hap[-l_bound:]
        l_bound = 0
    if r_bound > len(seq_read):
        seq_hap = seq_hap[:len(seq_read)-r_bound]
        r_bound = len(seq_read)
    if seq_read[l_bound:r_bound] == seq_hap:
        return True
    else:
        return False


def compare_sam_to_haps(
    f_vcf           :pysam.VariantFile,
    f_sam           :pysam.AlignmentFile,
    dict_ref_haps   :dict,
    dict_ref_gaps   :dict,
    dict_ref_cohorts:dict,
    dict_set_conflict_vars: dict, #For Debug only
    padding         :int=5
    ) -> dict:
    """
    Input:  f_sam file
    Output: ref bias dictionary according to variants
    """
    # build up the ref bias dictionary
    dict_ref_var_bias = {}
    for ref_name in dict_ref_haps.keys():
        dict_ref_var_bias[ref_name] = {}
        for start_pos in dict_ref_haps[ref_name]:
            # n_var has hap0, hap1, both, and others
            dict_ref_var_bias[ref_name][start_pos] = {'n_read':[0,0], 'n_var':[0,0,0,0], 'map_q':[0,0]}
    
    # parameters for pipeline design
    count_others  = [0,0]
    count_both    = [0,0]
    count_error   = [0,0]
    count_correct = [0,0]

    # scanning all the read alignments
    dict_errors = {}
    for segment in f_sam:
        flag = segment.flag
        if (flag & 4): # bitwise AND 4, segment unmapped
            continue
        # aligned read information
        ref_name     = segment.reference_name
        seq_name     = segment.query_name
        pos_start    = segment.reference_start # start position in genome coordiante, need +1 for vcf coordinate
        pos_end      = segment.reference_end
        cigar_tuples = segment.cigartuples
        mapq         = segment.mapping_quality
        rg_tag       = segment.get_tag("RG")
        read_seq     = segment.query_alignment_sequence # aligned sequence without SoftClip part
        
        related_vars = list(f_vcf.fetch(ref_name, pos_start, pos_end)) # list of pysam.variant
        #fetching the sequence in the read_seq regarding to the variant
        for var in related_vars:
            if var.start in dict_set_conflict_vars[ref_name]: # neglecting the conflict variant sites
                continue
            seq_hap0, seq_hap1 = dict_ref_haps[ref_name][var.start]

            match_flag_0 = False
            match_flag_1 = False
            # 1. Cohort alignment
            if dict_ref_cohorts[ref_name].get(var.start):
                cohort_start, cohort_seq0, cohort_seq1 = dict_ref_cohorts[ref_name][var.start]
                match_flag_0 = match_to_hap(pos_start, cohort_start, read_seq, cohort_seq0, cigar_tuples, padding)
                match_flag_1 = match_to_hap(pos_start, cohort_start, read_seq, cohort_seq1, cigar_tuples, padding)
                if match_flag_0 and match_flag_1:
                    if dict_ref_gaps[ref_name].get(var.start):
                        diff_hap0, diff_hap1 = dict_ref_gaps[ref_name][var.start]
                        diff_read = return_locate_cigar(
                                read_start=pos_start, 
                                target_pos=var.start, 
                                cigar_tuples=cigar_tuples
                                )
                        if diff_read == diff_hap0 and diff_read != diff_hap1:
                            match_flag_1 = False
                        elif diff_read != diff_hap0 and diff_read == diff_hap1:
                            match_flag_0 = False
                # 2. Cohort matchall comparison
                """
                if match_flag_0 == match_flag_1:
                    match_flag_0 = hap_inside(read_seq, cohort_seq0, padding)
                    match_flag_1 = hap_inside(read_seq, cohort_seq1, padding)
                    """
            # 3. Believeing local alignment
            flag_4 = False
            if match_flag_0 == match_flag_1: # both or others
                match_flag_0 = match_to_hap(pos_start, var.start, read_seq, seq_hap0, cigar_tuples, padding)
                match_flag_1 = match_to_hap(pos_start, var.start, read_seq, seq_hap1, cigar_tuples, padding)
                if match_flag_0 and match_flag_1:
                    if dict_ref_gaps[ref_name].get(var.start):
                        diff_hap0, diff_hap1 = dict_ref_gaps[ref_name][var.start]
                        diff_read = return_locate_cigar(
                                read_start=pos_start, 
                                target_pos=var.start, 
                                cigar_tuples=cigar_tuples
                                )
                        if diff_read == diff_hap0 and diff_read != diff_hap1:
                            match_flag_1 = False
                        elif diff_read != diff_hap0 and diff_read == diff_hap1:
                            match_flag_0 = False
            # 4. Matchall comparison
            
            if match_flag_0 == match_flag_1: # both or others
                flag_4 = True
                match_flag_0 = hap_inside(read_seq, seq_hap0, padding)
                match_flag_1 = hap_inside(read_seq, seq_hap1, padding)
                
            # 5. Assign Values
            if match_flag_0 and match_flag_1:
                dict_ref_var_bias[ref_name][var.start]['n_var'][2] += 1
            elif match_flag_0:
                dict_ref_var_bias[ref_name][var.start]['n_var'][0] += 1
            elif match_flag_1:
                dict_ref_var_bias[ref_name][var.start]['n_var'][1] += 1
            else:
                dict_ref_var_bias[ref_name][var.start]['n_var'][3] += 1
            
            # standard updating of read number and mapping quality
            if 'hapA' == rg_tag:
                dict_ref_var_bias[ref_name][var.start]['n_read'][0] += 1
                dict_ref_var_bias[ref_name][var.start]['map_q'][0]  += mapq
            elif 'hapB' == rg_tag:
                dict_ref_var_bias[ref_name][var.start]['n_read'][1] += 1
                dict_ref_var_bias[ref_name][var.start]['map_q'][1]  += mapq
            else:
                print("WARNING, there is a read without haplotype information!!")

            # TODO DEBUG PURPOSE!
            if seq_hap0 != seq_hap1: # only count heterozygous site
                if (len(var.ref) == 1 and max([len(seq) for seq in var.alts]) == 1):
                    gap_flag = 0
                else:
                    gap_flag = 1
                if match_flag_0 and match_flag_1:
                    count_both[gap_flag] += 1
                elif match_flag_0 == False and match_flag_1 == False:
                    count_others[gap_flag] += 1
                elif ('hapA' == rg_tag) and match_flag_0:
                    if flag_4 and gap_flag == 0:
                        if dict_errors.get(var.start):
                            dict_errors[var.start].append((int('hapA' == rg_tag), seq_name))
                        else:
                            dict_errors[var.start] = [(int('hapA' == rg_tag), var.start, seq_name)]
                    #    print(int('hapA' == rg_tag), var.start, seq_name)
                    count_correct[gap_flag] += 1
                elif ('hapB' == rg_tag) and match_flag_1:
                    if flag_4 and gap_flag == 0:
                        if dict_errors.get(var.start):
                            dict_errors[var.start].append((int('hapA' == rg_tag), seq_name))
                        else:
                            dict_errors[var.start] = [(int('hapA' == rg_tag), var.start, seq_name)]
                    #    print(int('hapA' == rg_tag), var.start, seq_name)
                    count_correct[gap_flag] += 1
                else:
                    """
                    if gap_flag == 0:
                        if dict_errors.get(var.start):
                            dict_errors[var.start].append((int('hapA' == rg_tag), seq_name))
                        else:
                            dict_errors[var.start] = [(int('hapA' == rg_tag), var.start, seq_name)]
                        #print(int('hapA' == rg_tag), var.start, seq_name)"""
                    count_error[gap_flag] += 1
    accumulate_error = list(dict_errors.items())
    print(len(accumulate_error))
    sorted_errors = sorted(accumulate_error, key=lambda x: len(x[1]), reverse=True)
    for idx in range(100):
        print("============", idx, "var.start", sorted_errors[idx][0], "=============")
        if len(sorted_errors[idx][1]) == 1:
            break
        for ele in sorted_errors[idx][1]:
            print(ele)
    print("count correct:", count_correct)
    print("count error:", count_error)
    print("count both:", count_both)
    print("count others:", count_others)
    return dict_ref_var_bias



def switch_var_seq(
        var     :pysam.VariantRecord,
        ref     :str,
        start   :int,
        genotype:int
        )-> tuple :
    """
    Switch the ref sequence according to the haplotype information
    """
    if genotype == 0:
        return ref, 0, len(var.ref)
    else:
        alt = var.alts[genotype - 1]
        return ref[:var.start-start] + alt + ref[var.stop-start:], len(var.ref) - len(alt), len(alt)


def variant_seq(
        f_vcf       :pysam.VariantFile,
        f_fasta     :pysam.FastaFile,
        var_chain   :int=15,
        padding     :int=5
        )-> tuple: # dict_set_conflict_vars, dict_var_haps, dict_cohort
    """
    Output
        dictionary containing the sequences nearby the variants
        - keys: ref_name
        - values: dict {}
                    - keys: var.start
                    - values: (seq_hap0, seq_hap1)
        set containing the conflict variants
        -values: dict_cohort {}
                    - keys: var.start
                    - values: (tuple)
                        - cohort start # anchor to the referene
                        - cohort seq 0 # chort seq still got paddings
                        - cohort seq 1
        - note: not include the variants within the padding distance to conflict variants
    """
    dict_ref_haps = {}
    dict_ref_gaps = {}
    dict_ref_cohorts = {}
    dict_set_conflict_vars = {}
    for ref_name in f_fasta.references:
        dict_ref_haps[ref_name] = {}
        dict_ref_gaps[ref_name] = {}
        dict_ref_cohorts[ref_name] = {}
        dict_set_conflict_vars[ref_name] = set()

    list_f_vcf = list(f_vcf)
    idx_vcf = 0 # While Loop Management
    while idx_vcf < len(list_f_vcf):
        var = list_f_vcf[idx_vcf]
        ref_name = var.contig
        
        cohort_vars = list(f_vcf.fetch(var.contig, var.start-var_chain, var.stop+var_chain))
        if len(cohort_vars) > 1: # the case where variants in the chaining area
            # Expanding to the chaining variants' chaining area
            cohort_start = min(var.start-var_chain, min([v.start-var_chain for v in cohort_vars]))
            cohort_maxstop = var.stop+var_chain
            for v in cohort_vars:
                cohort_maxstop = max(cohort_maxstop, max([v.start + len(a) + var_chain for a in v.alleles]))
            # Iterate until there are no variants in the chaining area
            while cohort_vars != list(f_vcf.fetch(var.contig, cohort_start, cohort_maxstop)):
                cohort_vars = list(f_vcf.fetch(var.contig, cohort_start, cohort_maxstop))
                cohort_start = min(cohort_start, min([v.start-var_chain for v in cohort_vars]))
                for v in cohort_vars:
                    cohort_maxstop = max(cohort_maxstop, max([v.start + len(a) + var_chain for a in v.alleles]))

            # Iterative parameters
            ref_seq = f_fasta.fetch(reference=var.contig, start= cohort_start, end = cohort_maxstop)
            seq_hap0, seq_hap1 = ref_seq, ref_seq
            adj_hap0, adj_hap1 = cohort_start, cohort_start
            diff_hap0, diff_hap1     =  0,  0
            overlap0,  overlap1      =  0,  0
            prev_start0, prev_start1 = -1, -1
            # parameters for cohort records
            indel_flag    = False
            conflict_flag = False
            # parameters keep track of the var positions
            list_start_hap = [[],[]]
            list_len_hap   = [[],[]]
            for c_var in cohort_vars: # Modify the iterative parameters
                hap_0, hap_1 = c_var.samples[0]['GT']
                if c_var.start > prev_start0 + overlap0: # checking if there are overlaps
                    adj_hap0 += diff_hap0
                    seq_hap0, diff_hap0, len_var= switch_var_seq(c_var, seq_hap0, adj_hap0, hap_0)
                    prev_start0 = c_var.start
                    overlap0 = len_var - 1 if (diff_hap0 == 0) else diff_hap0
                    list_start_hap[0].append(c_var.start - adj_hap0)
                    list_len_hap[0].append(len_var)
                else: # overlapping variants are consider conflicts
                    list_start_hap[0].append(-1)    # house keeping
                    list_len_hap[0].append(-1)      # house keeping
                    conflict_flag = True            # conflicts in the cohort
                    dict_set_conflict_vars[ref_name].add(prev_start0)
                    dict_set_conflict_vars[ref_name].add(c_var.start)
                if c_var.start > prev_start1 + overlap1:
                    adj_hap1 += diff_hap1
                    seq_hap1, diff_hap1, len_var = switch_var_seq(c_var, seq_hap1, adj_hap1, hap_1)
                    prev_start1 = c_var.start
                    overlap1 = len_var - 1 if (diff_hap1 == 0) else diff_hap1
                    list_start_hap[1].append(c_var.start - adj_hap1)
                    list_len_hap[1].append(len_var)
                else:
                    list_start_hap[1].append(-1)
                    list_len_hap[1].append(-1)
                    conflict_flag = True
                    dict_set_conflict_vars[ref_name].add(prev_start1)
                    dict_set_conflict_vars[ref_name].add(c_var.start)
                if diff_hap0 != 0 or diff_hap1 != 0:
                    dict_ref_gaps[ref_name][c_var.start] = (diff_hap0, diff_hap1)
                    indel_flag = True

            for idx, c_var in enumerate(cohort_vars):
                start0 = list_start_hap[0][idx]
                start1 = list_start_hap[1][idx]
                seq_0 = seq_hap0[start0 - padding:start0 + list_len_hap[0][idx] + padding]
                seq_1 = seq_hap1[start1 - padding:start1 + list_len_hap[1][idx] + padding]
                if dict_ref_haps[ref_name].get((c_var.start)):
                    print("WARNNING! Duplicate variant at contig:", var.contig, ",pos:", c_var.start)
                dict_ref_haps[ref_name][(c_var.start)] = (seq_0, seq_1)
            if indel_flag and not conflict_flag: # only generate the cohort if there are indels and no conflict alleles
                seq_hap0 = seq_hap0[var_chain-padding:start0 + list_len_hap[0][idx] + padding]
                seq_hap1 = seq_hap1[var_chain-padding:start1 + list_len_hap[1][idx] + padding]
                for c_var in cohort_vars:
                    dict_ref_cohorts[ref_name][(c_var.start)] = (var.start, seq_hap0, seq_hap1)
            idx_vcf += len(cohort_vars) # While Loop Management
        else: # single variant
            var_start = var.start - padding
            var_stop  = var.stop  + padding
            ref_seq = f_fasta.fetch(reference=var.contig, start= var_start, end = var_stop)
            hap_0, hap_1 = var.samples[0]['GT']
            seq_hap0,diff_hap0,_ = switch_var_seq(var, ref_seq, var_start, hap_0)
            seq_hap1,diff_hap1,_ = switch_var_seq(var, ref_seq, var_start, hap_1)
            if dict_ref_haps[ref_name].get((var.start)):
                print("WARNNING! Duplicate variant at contig:", var.contig, ",pos:", var.start)
            dict_ref_haps[ref_name][(var.start)] = (seq_hap0, seq_hap1)
            if diff_hap0 != 0 or diff_hap1 != 0:
                dict_ref_gaps[ref_name][var.start] = (diff_hap0, diff_hap1)
            idx_vcf += 1 # While Loop Management
        
    return dict_set_conflict_vars, dict_ref_haps, dict_ref_cohorts, dict_ref_gaps




if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--vcf', help='vcf file')
    parser.add_argument('-s', '--sam', help='sam file')
    parser.add_argument('-f', '--fasta', help='reference fasta file')
    parser.add_argument('-o', '--out', help='output file')
    args = parser.parse_args()
    
    fn_vcf = args.vcf
    fn_sam = args.sam
    fn_fasta = args.fasta
    fn_output = args.out
    
    f_vcf   = pysam.VariantFile(fn_vcf)
    f_sam   = pysam.AlignmentFile(fn_sam)
    f_fasta = pysam.FastaFile(fn_fasta)
    #var_chain = 15
    padding = 5
    var_chain = 25
    #padding   = 10
    print("Start building the variant maps...")
    dict_set_conflict_vars, dict_ref_haps, dict_ref_cohorts, dict_ref_gaps = variant_seq(
            f_vcf=f_vcf,
            f_fasta=f_fasta,
            var_chain=var_chain,
            padding=padding)
    #print(dict_ref_gaps['chr21'][15149896])
    # extend conflict set
    for ref_name in dict_set_conflict_vars.keys():
        for pos in list(dict_set_conflict_vars[ref_name]):
            for extend in range(pos-var_chain, pos+var_chain):
                dict_set_conflict_vars[ref_name].add(extend)
    
    print("Start comparing reads to the variant map...")
    dict_ref_bias = compare_sam_to_haps(
            f_vcf=f_vcf,
            f_sam=f_sam,
            dict_ref_haps=dict_ref_haps,
            dict_ref_gaps=dict_ref_gaps,
            dict_ref_cohorts=dict_ref_cohorts,
            dict_set_conflict_vars=dict_set_conflict_vars,
            padding=padding)
    
    f_vcf   = pysam.VariantFile(fn_vcf)
    print("Start output report...")
    output_report(
            f_vcf=f_vcf,
            dict_ref_bias=dict_ref_bias,
            dict_set_conflict_vars=dict_set_conflict_vars, 
            fn_output=fn_output)


