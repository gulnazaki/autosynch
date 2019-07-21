"""
References:
- J. Dedina and H. C. Nusbaum. "PRONOUNCE: a program for pronunciation by
  analogy." Comput. Speech Lang. 5(1), 1991, pp. 55-64.
- Y. Marchand and R. I. Damper. "A multistrategy approach to improving
  pronunciation by analogy." Comput. Linguist. 26(2), 2000, pp. 196-219.
- Y. Marchand and R. I. Damper. "Can syllabification improve pronunciation by
  analogy of English?" Nat. Lang. Eng. 13(1) 2006, pp. 1-24.
"""

import os
import re
from num2words import num2words
from collections import Counter, deque
from operator import itemgetter

from autosynch.config import cmudict_path, nettalk_path

class SyllableCounter(object):
    def __init__(self, sba_lexicon_path=nettalk_path, cmudict_path=cmudict_path):
        self.regex = re.compile("[^a-zA-Z\s']+")
        self.lexicon, self.counter = self._load_data(sba_lexicon_path, cmudict_path)

    def _load_data(self, sba_lexicon_path, cmudict_path):
        lexicon = []
        counter = {}

        try:
            with open(sba_lexicon_path, 'r') as f:
                sba_lexicon = f.read().splitlines()
        except Exception as e:
            print(e)
            return None, None

        try:
            with open(cmudict_path, 'r') as f:
                cmudict = f.read().splitlines()
        except Exception as e:
            print('Unable to read CMUdict')
            cmudict = []

        for line in sba_lexicon:
            if not line or line.startswith('#'):
                continue
            line = line.split()
            word = line[0]
            syll = line[2]
            count = 0

            hyphenated_word = ''
            for i, ch in enumerate(word):
                if i < len(word)-1 and syll[i] != '>' and syll[i+1] != '<':
                    hyphenated_word += ch + '-'
                    count += 1
                else:
                    hyphenated_word += ch + '*'

            lexicon.append('#{}#'.format(hyphenated_word[:-1]))
            counter[word] = count + 1

        for line in cmudict:
            if not line or line.startswith(';;;'):
                continue
            word = line.split(None, 1)[0].lower()
            count = sum(ch.isdigit() for ch in line)

            if word.endswith(')'):
                continue

            if word not in counter or counter[word] < count:
                counter[word] = count

        return lexicon, counter

    def _naive(self, input):
        vowels = 'aeiouy'

        n_vowels = 0
        prev_vowel = False

        for ch in input:
            is_vowel = False
            if ch in vowels:
                if not prev_vowel:
                    n_vowels += 1
                is_vowel = True
                prev_vowel = True

            if not is_vowel:
                prev_vowel = False
        if input.endswith('es') or input.endswith('e'):
            n_vowels -= 1

        return n_vowels

    def _sba(self, input, verbose=False):
        # Node data class
        class data(object):
            def __init__(self):
                self.outputs = Counter() # Set of arcs going out
                self.sinputs = [] # Set of arcs coming in, filled by BFS
                self.distance = float('inf') # From origin, filled by BFS

        # Format input
        input = '#{}#'.format(input.replace('', '*')[1:-1])

        # Pronunciation lattice
        lattice = {('#', 0): data(), ('#', len(input)-1): data() }

        # Substring matcher and lattice builder
        substring = []
        for entry in self.lexicon:
            for offset in range(-len(input)+3, len(entry)-2):
                for i in range(max(0, -offset), min(len(input), len(entry)-offset)):
                    if input[i] == entry[i+offset] or (input[i] == '*' and entry[i+offset] == '-'):
                        substring.append((entry[i+offset], i))
                    else:
                        for i, node in enumerate(substring):
                            string = ''
                            if node not in lattice:
                                lattice[node] = data()
                            for j in range(i+1, len(substring)):
                                string += substring[j][0]
                                arc = (substring[j], string[:-1])
                                lattice[node].outputs[arc] += 1
                        substring.clear()

                for i, node in enumerate(substring):
                    string = ''
                    if node not in lattice:
                        lattice[node] = data()
                    for j in range(i+1, len(substring)):
                        string += substring[j][0]
                        arc = (substring[j], string[:-1])
                        lattice[node].outputs[arc] += 1

        # Decision function 1: get shortest path(s)
        queue = deque([('#', 0)])
        lattice[('#', 0)].distance = 0
        while queue:
            node = queue.popleft()
            for out_arc in lattice[node].outputs:
                adjacent = out_arc[0]
                in_arc = (node, out_arc[1], lattice[node].outputs[out_arc])
                if lattice[node].distance + 1 < lattice[adjacent].distance:
                    queue.append(adjacent)
                    lattice[adjacent].distance = lattice[node].distance + 1
                    lattice[adjacent].sinputs.append(in_arc)
                elif lattice[node].distance + 1 == lattice[adjacent].distance:
                    lattice[adjacent].sinputs.append(in_arc)
        queue.clear()

        # Decision function 2: score by strategy
        # PF = product, SDPS = standard deviation, WL = weak link
        # Calculate scores
        paths = []
        def dfs(node, path, arcs):
            if node == ('#', 0):
                pf, sdps, wl = 1, 0, float('inf')
                mean = sum(arcs)/len(arcs)
                for arc in arcs:
                    pf *= arc
                    sdps += (arc-mean)**2
                    wl = min(wl, arc)
                sdps /= len(arcs)

                paths.append((path, pf, sdps, wl))
                return
            if not lattice[node].sinputs:
                return

            path = node[0] + path
            for arc in lattice[node].sinputs:
                _arcs = arcs[:]
                _arcs.append(arc[2])
                dfs(arc[0], arc[1]+path, _arcs)

        dfs(('#', len(input)-1), '', [])
        if not paths:
            if verbose:
                print('UserWarning: No syllabification found')
            return None

        # Assign point values
        scores = {path[0]: 0 for path in paths}
        for s in range(1, 4):
            ranking = sorted(paths, key=itemgetter(s), reverse=True)
            rank, cand, cval = len(paths), 0, ranking[0][s]

            for i, path in enumerate(ranking):
                if path[s] < cval:
                    points = rank - (cand-1)/2
                    for t in ranking[i-cand:i]:
                        scores[t[0]] += points
                    rank -= 1
                    cand, cval = 1, path[s]
                else:
                    cand += 1

            points = rank - (cand-1)/2
            for t in ranking[-cand:]:
                scores[t[0]] += points

        shortest_path = max(scores.items(), key=itemgetter(1))[0]
        n_syllables = shortest_path.count('-') + 1

        return n_syllables

    def _build_lyrics(self, lyrics):
        formatted_lyrics = []
        section = []

        lines = lyrics.splitlines()
        for line in lines:
            if line.startswith('[') and line.endswith(']'):
                if 'Produced' in line:
                    continue
                if section:
                    formatted_lyrics.append(section[:])
                    section.clear()
            elif line:
                line = line.replace('-', ' ').replace('—', ' ').replace('/', ' ')
                section.append([word for word in line.split()])
        formatted_lyrics.append(section)

        return formatted_lyrics

    def get_syllable_count_word(self, word):
        try: # word is numerical
            word = num2words(float(word)).replace('-', ' ')
            return sum([self.get_syllable_count_word(word) for word in word.split()])
        except ValueError:
            word = self.regex.sub('', word).lower() # lowercase, no punctuation

        if word in self.counter:
            return self.counter[word]

        n_syllables = self._sba(word.replace("'", '')) # if not common contraction, remove apostrophe
        if n_syllables is None:
            n_syllables = self._naive(word)
        self.counter[word] = n_syllables

        return n_syllables

    def get_syllable_count_lyrics(self, lyrics):
        formatted_lyrics = self._build_lyrics(lyrics)

        syl_lyrics = []
        syl_section = []
        for section in formatted_lyrics:
            for line in section:
                syl_section.append([self.get_syllable_count_word(word) for word in line])
            syl_lyrics.append(syl_section[:])
            syl_section.clear()

        return syl_lyrics