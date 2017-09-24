#!/usr/bin/env python
#
# Given an call sequence specification file (gcs) and an input file (or stdin)
# in CSV format, generate the call sequence using Chrome's trace event viewer
#
# Copyright 2017 Aleksandr Koltsoff (czr@iki.fi)
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0
#
# Canonical project URL:
# https://github.com/majava3000/slib-tools/tree/master/generate-call-sequence
#
# NOTE:
# - Does not currently handle sequences that start "mid-way" into the call
#   sequence. Input data must start by an start code and from initial "call
#   depth" of zero. This restriction will be lifted in future.
# - "Dangling" calls at the end of sequence are implicitly automatically closed
#   at the end, resulting in somewhat "unreal" results. This seemed the most
#   useful method of dealing with the issue.
# - For instructions on usage and use cases, please see README.md in this
#   directory.

from __future__ import print_function
import sys
import re
import string
import collections

symbolRES = "[a-zA-Z0-9_]+"
singleCharRES = "[a-zA-Z]"
hexRES = "0x[a-fA-F0-9]+"
decimalRES = "[0-9]+"
# code specifiers are non-colliding, so order does not really matter. however,
# prefer longest/most unique matches first
codeSpecifierRES = "%s|%s|%s" % (hexRES, singleCharRES, decimalRES)

# label must always be present, and attempt to match longest possible matches
# first
validSpecRE = re.compile(r"^(%s):((%s),(%s),(%s)|(%s),(%s)|(%s))$" % (
  symbolRES,
  codeSpecifierRES, codeSpecifierRES, symbolRES,
  codeSpecifierRES, codeSpecifierRES,
  codeSpecifierRES) )

# helper to convert given code specifier into an integer (None passes through)
def codeSpecifierAsInt(s):
  # we could reuse the REs from above, but that would be overkill
  if s == None:
    return None
  if s.startswith('0x'):
    return int(s, 16)
  if s[0] in string.digits:
    return int(s)
  return ord(s)

# parse and return the call sequence spec
# returns:
# ((label, entryData, leaveData|None, start-context|None), ...)
# Returns None if there were parsing errors (errors are output on stderr)
# NOTE: Does not validate the spec semantically (only syntax)
def parseSpec(input):
  # collect the entries here
  res = []
  lineNumber = 1
  haveErrors = False

  for line in input:
    # just the the bit before any comment
    content = line.split('#', 1)[0]
    # remove all whitespace from the line
    content = "".join(content.split())
    if len(content) > 0:

      # print("'%s'" % (content,))
      matcho = validSpecRE.match(content)
      if matcho == None:
        print("ERROR(%s:%u): '%s' is not valid spec entry" % (
          input.name, lineNumber, content), file=sys.stderr)
        haveErrors = True
      else:
        groups = matcho.groups()
        label = groups[0]
        # prepare the event (we still need to convert the code specifiers into
        # integers)
        ev = None
        if groups[-1] != None:
          # single event matcher, easiest
          #   ('single', 'D', None, None, None, None, None, 'D')
          ev = [label, groups[-1], None, None]
        elif groups[-2] != None:
          # entry and exit defined, but no new context
          #   ('powerdown', 'G,g', None, None, None, 'G', 'g', None)
          ev = [label, groups[-3], groups[-2], None]
        else:
          # full three entry spec entry
          #   ('complete1', 'B,b,COMP_ISR1', 'B', 'b', 'COMP_ISR1', None, None, None)
          ev = [label, groups[-6], groups[-5], groups[-4]]
        # print(matcho.groups())
        # print(ev)

        ev[1] = codeSpecifierAsInt(ev[1])
        ev[2] = codeSpecifierAsInt(ev[2])
        res.append(tuple(ev))

    lineNumber += 1

  if haveErrors:
    return None

  return res

# verify that the spec is semantically valid.
# since we haven't yet seen input data, we can just make checks that the used
# codes are unique
# Specifically, check that:
# - labels are unique (across labels)
# - data specifiers are unique (across data specifiers)
# - context entry names are unique (across context entry names)
#
# Returns True/False based on validity, will emit to stderr if semantic issues
# are found.
def isSpecSemanticallyValid(spec):
  # will contain space:k -> num-of-duplicates (0 = no duplicates). Will not
  # include counters for values that are none
  checkSpace = collections.Counter()

  # we will run checkMap 4 times for each spec entry, in the order of l,s,s,c
  # any entry in spec that is None is skipped over (to simplify logic later)
  entrySpaceNames = "lssc"
  for specEntry in spec:
    for x in range(4):
      v = specEntry[x]
      if v != None:
        k = "%s:%s" % (entrySpaceNames[x], v)
        checkSpace[k] += 1

  # pick entries whose value is above 1 indicating a duplicate. we use items()
  # here instead of iteritems to support py2/py3 (not perf-critical)
  dups = [(k,v) for k,v in checkSpace.items() if v > 1]
  # print("Duplicates: %s" % str(dups) )
  if len(dups) > 0:
    longNames = { 'l': 'label',
                  's': 'code',
                  'c': 'context' }
    for k,v in sorted(dups):
      print("ERROR(semantic): %s '%s' defined %u times" % (
        longNames[k[0]], k[2:], v), file=sys.stderr )

    return False

  # No duplicates, spec seems valid semantically
  return True

class NestedBuilder:

  # We have three kinds of actions that the incoming codes can represent:
  # - return
  # - enter, label, new-context-label|None
  #   if new-context label is present, it will create a new context anchor
  # - mark, label (does not cause stack movement)
  ACTION_ENTER = 0
  ACTION_RETURN = 1
  ACTION_MARK = 2

  actionNames = [ "ENTER", "RETURN", "MARK" ]

  # create new builder using the spec
  def __init__(self, spec):
    # this map will contain code -> (action, label, context) based on spec
    self.codeMap = {}
    # once we get data from CSV, we'll collect the actions here
    self.actions = []
    # once we're resolving, this will hold the current stack of
    # [startTS, label, context] entries
    self.stack = []
    # emitted events will be collected here
    # [startTS, label, duration|None] (None for marks)
    # [startTS, "sctx:label", None] for start context marker
    # [startTS, "ectx:label", None] for end context marker
    self.emit = []

    # convert the spec into format that allows relatively painless lookup
    for label, enterCode, returnCode, contextName in spec:
      if returnCode == None:
        self.codeMap[enterCode] = (self.ACTION_MARK, label, None)
      else:
        self.codeMap[returnCode] = (self.ACTION_RETURN, label, contextName)
        self.codeMap[enterCode] = (self.ACTION_ENTER, label, contextName)

  # returns False if code cannot be recognized.
  # does not check for time going backward (up to caller)
  def addEvent(self, ts, code):
    if code not in self.codeMap:
      return False
    self.actions.append((ts, self.codeMap[code]))
    return True

  # convenience function that returns string suitable for indentation based on
  # current stack depth
  def getStackIndent(self):
    return " " * len(self.stack)

  # unwind and emit top of the stack. ts is the emit point timestamp
  # context is also the context of the event, currently unused
  # returns the duration of removed entry
  def unwindOne(self, ts):

    assert(len(self.stack) > 0)

    startedAt = self.stack[-1][0]
    duration = ts - startedAt      
    self.emit.append((startedAt, self.stack[-1][1], duration))
    del self.stack[-1]

    # update context tracking
    newContext = None
    if len(self.stack) > 0:
      newContext = self.stack[-1][-1]
    self.trackContext(ts, newContext)

    return duration

  # handles emitting of context changing operations
  def trackContext(self, ts, newContext):
    # if context doesn't change, no need to do anything
    if newContext == self.currentContext:
      return

    if self.currentContext != None:
      # emit end of context first using current
      self.emit.append((ts, "ectx:%s" % self.currentContext, None))
    self.currentContext = newContext
    if self.currentContext != None:
      # emit start of context next
      self.emit.append((ts, "sctx:%s" % self.currentContext, None))

  # this does the heavy lifting in resolving the actions
  def resolveActions(self):

    if len(self.actions) == 0:
      return

    # for ts, event in self.actions:
    #   print("%.15f: %s %s" % (ts, self.actionNames[event[0]], event[1:]))

    self.currentContext = None

    for ts, ev in self.actions:
      action, label, context = ev[0], ev[1], ev[2]
      if action == self.ACTION_ENTER:
        # push to stack
        #print("%s %s (startAt=%.9f)" % (self.getStackIndent(), label, ts))
        # if this event does not carry context, propagate the current one
        if context == None:
          context = self.currentContext
        self.trackContext(ts, context)
        self.stack.append((ts, label, context))
      elif action == self.ACTION_MARK:
        #print("%s MARK(%s) (at=%.9f)" % (self.getStackIndent(), label, ts))
        self.emit.append((ts, label, None))
      else:
        # leave
        while len(self.stack) > 0 and self.stack[-1][1] != label:
          unwindLabel = self.stack[-1][1]
          dur = self.unwindOne(ts)
          print("WARNING: unwinding %s implicitly (duration %.9f s)" % (
            unwindLabel, self.getStackIndent(), duration), file=sys.stderr)
        if len(self.stack) == 0:
          print("WARNING: unwound all stack without finding start of %s" % label,
                file=sys.stderr)
        else:
          dur = self.unwindOne(ts)
          # print("%s <- dur=%.9f" % (self.getStackIndent(), dur))

    # unwind remaining entries
    # use the last timestamp of events as the ending point
    # use unwindUntilLabel(ts, None), so it will never match)
    #  which will use unwindOne(ts)
    ts = self.actions[-1][0]
    while len(self.stack) > 0:
      unwindLabel = self.stack[-1][1]
      dur = self.unwindOne(ts)
      print("WARNING: Unwinding %s implicitly at end of trace" % unwindLabel,
            file=sys.stderr)

    # custom comparison for emit entries to get correct ordering when the
    # context start/end emit entries are present (a linear transform using
    # regular key= escapes me, better approach appreciated)
    def priorityCmp(a, b):
      # rules:
      #  1) ts always wins
      tsa, tsb = a[0], b[0]
      # cannot use cmp, since python3 doesn't have it
      # ( https://docs.python.org/3.0/whatsnew/3.0.html )
      cr = ((tsa>tsb)-(tsa<tsb))
      if cr != 0:
        return cr

      # either side or both are context instructions (rules and precedence)
      #  2) context-end is before context-start (ie, context switch)
      #  3) context-end is after anything else at the same time (can this be
      #     solved together with 1 though?)
      #  4) context-start is before anything else at the same time
      #
      # we can express this as the following table:
      #     a     |      b      ||   result
      #  non-ctx  |    non-ctx  ||   cmp(la,lb)
      #  non-ctx  |      c-end  ||     -1 (select a)
      #  non-ctx  |    c-start  ||      1 (select b)
      #    c-end  |    non-ctx  ||      1 (select b)
      #    c-end  |      c-end  ||   cmp(la, lb) (combination shouldn't happen)
      #    c-end  |    c-start  ||     -1 (select a)
      #  c-start  |    non-ctx  ||     -1 (select a)
      #  c-start  |      c-end  ||      1 (select b)
      #  c-start  |    c-start  ||   cmp(la, lb) (combination shouldn't happen)
      # Internally we'll encode zero as a signal to do a comparison based on
      # labels (which will deal with the colon when required)
      # Use s.split(":", 1)[-1] (picks the right side in both cases)
      akey = None
      if ':' in a[1]:
        akey = a[1].split(':', 1)[0]
      bkey = None
      if ':' in b[1]:
        bkey = b[1].split(':', 1)[0]
      skey = (akey,bkey)
      #print(skey)
      # map of the rules k=(akey, bkey)
      srules = {
        (  None,   None):  0,
        (  None, "ectx"): -1,
        (  None, "sctx"):  1,
        ("ectx",   None):  1,
        ("ectx", "ectx"):  0,
        ("ectx", "sctx"): -1,
        ("sctx",   None): -1,
        ("sctx", "ectx"):  1,
        ("sctx", "sctx"):  0
      }
      cr = srules[skey]
      # 0 here means that both sides were plain, or that both sides were
      # the same context type. In both cases, we should just return the result
      # of comparison using the original keys, otherwise return the value from
      # the table as is
      if cr == 0:
        # was a plain-vs-plain comparison
        return ((a[1]>b[1])-(a[1]<b[1]))
      return cr

    # this is copied verbatim from https://docs.python.org/3/howto/sorting.html#sortinghowto
    # urgh. makes an python2 cmp-like wrapper for key-based sorter
    def cmp_to_key(mycmp):
      class K:
        def __init__(self, obj, *args):
          self.obj = obj
        def __lt__(self, other):
          return mycmp(self.obj, other.obj) < 0
        def __gt__(self, other):
          return mycmp(self.obj, other.obj) > 0
        def __eq__(self, other):
          return mycmp(self.obj, other.obj) == 0
        def __le__(self, other):
          return mycmp(self.obj, other.obj) <= 0
        def __ge__(self, other):
          return mycmp(self.obj, other.obj) >= 0
        def __ne__(self, other):
          return mycmp(self.obj, other.obj) != 0
      return K

    # sort the event into proper order, taking into account the context
    # switching markers
    self.emit.sort(key=cmp_to_key(priorityCmp))

  def emitTraceJSON(self, output):
    # right, form the data into json for consumption
    # three kinds of events are emitted
    print("[", end='', file=output)
    for idx in range(len(self.emit)):
      ts, label, dur = self.emit[idx]
      # print(ts,label,dur)
      # Durations are in usecs for the trace viewer
      ts = "%.3f" % (ts * 1000000)
      if dur != None:
        # event with duration (ph=X)
        dur = "%.3f" % (dur * 1000000)
        print('{"name":"%s","ts":%s,"dur":%s,"pid":0,"tid":0,"ph":"X","cat":"func","args":{}}' % (
          label, ts, dur), end='', file=output)
      else:
        if ':' in label:
          # context switch mark (ph=b|e)
          name = label.split(":", 1)[-1]
          ph = "b"
          if label.startswith('ectx:'):
            ph = "e"
          print('{"name":"%s","cat":"context","ts":%s,"pid":0,"ph":"%s","id":"0x0"}' % (
            name, ts, ph), end='', file=output)
        else:
          # regular mark (ph=i). use process wide mark to make it more visible
          print('{"name":"%s","ts":%s,"pid":0,"ph":"i","s":"p"}' % (
            label, ts), end='', file=output)
      if len(self.emit) > 1 and idx < len(self.emit)-1:
        print(",", file=output)
    print("]", file=output)

if __name__ == '__main__':

  import argparse

  description = "Convert CSV formatted event list into trace data for Chrome"
  optParser = argparse.ArgumentParser(description=description)
  optParser.add_argument('specfile', type=argparse.FileType('r'),
                         help="File to use as the specification for decoding")
  optParser.add_argument('csvfile', nargs='?', type=argparse.FileType('r'),
                         default=sys.stdin,
                         help="File to read events from (if not stdin)")
  optParser.add_argument('outfile', nargs='?', type=argparse.FileType('w'),
                         default=sys.stdout,
                         help="File to write to (if not stdout)")
  args = optParser.parse_args()

  spec = parseSpec(args.specfile)
  if spec == None:
    print("ERROR: There was one or more syntax error in the specification", file=sys.stderr)
    sys.exit(1)
  if not isSpecSemanticallyValid(spec):
    print("ERROR: There was one or more semantic error in the specification", file=sys.stderr)
    sys.exit(1)

  # for s in spec:
  #   print(s)

  builder = NestedBuilder(spec)

  # start processing the csv input and make a list of events
  lineNumber = 1
  # validate the timestamps increase
  prevTS = None
  for line in args.csvfile:
    # skip over the first line and any line that starts with #
    if lineNumber == 1 or line.startswith('#'):
      lineNumber += 1
      continue
    comps = line.split(",")[:2]
    ts, code = float(comps[0]), int(comps[1])
    if prevTS != None:
      if prevTS > ts:
        print("ERROR(%s:%u): Timestamp goes backwards" % (csvInput.name, lineNumber), file=sys.stderr)
        sys.exit(1)
    prevTS = ts
    #print(ts, code)
    if not builder.addEvent(ts, code):
      print("ERROR(%s:%u): code %u is unknown" % (csvInput.name, lineNumber, code), file=sys.stderr)
      sys.exit(1)

    lineNumber += 1

  builder.resolveActions()
  builder.emitTraceJSON(args.outfile)
