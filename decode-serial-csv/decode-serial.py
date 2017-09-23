#!/usr/bin/env python
#
# Decode uart data and convert into CSV formatted as:
# ts, byte(unsigned), isFrameValid(0|1), printable(subascii)
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
# https://github.com/majava3000/slib-tools/tree/master/decode-serial-csv
#
# Technical notes:
# - Assumes python float is 64-bit wide, otherwise things will break.
# - For instructions on usage and use cases, please see README.md in this
#   directory.
# - Should work identically in more recent python 2 and python 3
#

from __future__ import print_function
import copy
import string
import sys

# Ordered list of timestamp+newValue entries with input filtering and fixation
# with optional post-last-change tail-length extension (default 10 units)
# (each column from the input CSV except the timestamp will get one object by
#  default)
class Channel():

  def __init__(self, name):
    self.name = name
    self.entries = []

  # add one entry to the channel. if value same as before, no change
  # will assert if time is same or goes backward
  def add(self, eventTS, eventValue):

    if len(self.entries) == 0:
      self.entries.append((eventTS, eventValue))
      return

    prev = self.entries[-1]
    assert(eventTS > prev[0])
    if eventValue != prev[1]:
      self.entries.append((eventTS, eventValue))

  # convert the list into tuple, but add a guard region of given length to the
  # end
  def finishAdding(self, tailLength=10):
    if tailLength > 0.0:
      assert(len(self.entries) > 0)
      prev = self.entries[-1]
      # replicate the value into future
      self.entries.append((prev[0] + tailLength, prev[1]))
    self.entries = tuple(self.entries)

  def __repr__(self):
    return "<Channel(%s). ec=%u>" % (self.name, len(self.entries))

# read in an saleae csv export (changed based, header, with commas and separate
# columns for each)
# timestamps are kept in double format, channels are decoupled
# each channel track consists of:
#  [(ts, level), (ts2, level2)] although level2 != level always.
# note that we decode everything although we're really only interested in a
# single channel.
# TODO: add the filtering later, and make this perhaps a bit more generic
# the number of decimal places of input is also returned. unnecessary trailing
# zeros are not included in this number
def parseSaleaeCSV(fobject):
  # we don't know how many columns are coming in yet
  channels = []
  # track number of decimal places
  tsDecimals = 0

  for line in fobject:
    comps = [ x.strip() for x in line.split(",") ]
    if len(channels) == 0:
      # we now know how many tracks, but not yet the starting values
      assert(comps[0] == "Time[s]")
      for name in comps[1:]:
        channels.append(Channel(name))
      channels = tuple(channels)
    else:
      # drop unnecessary zeros from the end, although there seems to be a
      # rounding/imprecision issue in saleae, since it sometimes emits stuff
      # like 4.750203954000001 while otherwise all decimals are zero at the end
      tsStr = comps[0].rstrip('0')
      ts = float(tsStr)
      tsDecimals = max(tsDecimals, len(tsStr.split(".")[-1]))
      for chanIdx in range(len(channels)):
        channels[chanIdx].add(ts, int(comps[1+chanIdx]))

  # add tails and convert into immutable sequence
  for chan in channels:
    chan.finishAdding()

  return channels, tsDecimals

# custom exception to mark condition where advanced too far into the future
# this is actually expected at end, but will simplify the processor
class ChannelCursorOutOfRangeException(Exception):
  pass

class ChannelCursor():

  def __init__(self, channel):
    assert(len(channel.entries) > 0)
    # instead of keeping the channel hanging around, we just ref the entries
    # of the chan (they're tuples at this point)
    self.entries = channel.entries
    # cursor is set at initial position
    self.curIndex = 0
    # setup current position to start of the first event
    self.curPosition = self.entries[0][0]
    self.startOfNextEntry = self.getStartOfNextEntry()

  # return start of next entry, except if at end, will return the same
  def getStartOfNextEntry(self):
    if self.curIndex < (len(self.entries)-1):
      return self.entries[self.curIndex+1][0]
    return self.entries[self.curIndex][0]

  # get current position (even if past tail)
  def getPosition(self):
    return self.curPosition

  # return None once past tail, otherwise value from current position
  def getValue(self):
    return self.entries[self.curIndex][1]

  # return true if at end
  def isAtEnd(self):
    return self.curIndex >= len(self.entries)

  # internal helper to raise exception if at end
  def raiseIfAtEnd(self):
    if self.isAtEnd():
      raise ChannelCursorOutOfRangeException("Cursor passed end")

  # advance position into the future by given amount
  # if this crosses one or more event boundary, will update the event copy
  def advance(self, advanceBy):

    while (self.curPosition + advanceBy >= self.startOfNextEntry):
      # jump to next entry if there's still something to jump to

      self.curIndex += 1
      self.raiseIfAtEnd()
      self.startOfNextEntry = self.getStartOfNextEntry()

    # reached the proper position, update curPosition
    self.curPosition += advanceBy

  # advance until next time that value changes to given one
  # note that if value is already at targetValue, scan will start only after
  # it changes first once
  def advanceUntilChangeTo(self, targetValue):

    self.raiseIfAtEnd()

    origIndex = self.curIndex

    # start by advancing to the next entry always first
    self.advance(self.startOfNextEntry - self.curPosition)

    assert(self.curIndex != origIndex)
    # if current value does not match targetValue, we need to go one forward
    if self.getValue() != targetValue:
      self.advance(self.startOfNextEntry - self.curPosition)

    # we're at the target value

  def __repr__(self):
    return "<ChannelCursor: %.8f/%.8f/%.8f cI=%u eC=%u>" % (
      self.curPosition, self.startOfNextEntry, self.entries[-1][0],
      self.curIndex, len(self.entries))

# return list of tuples:
# (timestamp, int-data(0-255), True|False based on frame recognition success)
def recognizeUART(channel, baudrate, dataBitsPerFrame=8, omitInvalidFrames=True):
  c = ChannelCursor(channel)
  bitperiod = 1 / float(baudrate)

  while True:
    try:
      # 1) find next transition to 0 and record position
      c.advanceUntilChangeTo(0)
      eventStartsAt = c.getPosition()

      # 1b) peek into half bitperiod for stable START. since advance only works
      # forward, it's easier to make a copy of the cursor at this point and
      # work with that while peeking. sparse copy is intentional.
      peeker = copy.copy(c)
      peeker.advance(bitperiod / 2)
      if not peeker.getValue() == 0:
        # START wasn't stable, advance starting point by half bitperiod and
        # try again
        c.advance(bitperiod / 2)
        continue

      # 2) START is stable, but we're still at the original starting position
      #    advance to the midpoint of the first bit
      c.advance(bitperiod * 1.5)

      # 3) collect the next 8 bits into data (don't collect STOP)
      data = 0
      factor = 1
      for x in range(dataBitsPerFrame):
        bit = c.getValue()
        # print("Bit(%u)=%u" % (x, bit), end='')
        data += factor * bit
        # print(" data=%u, factor=%u" % (data, factor))
        c.advance(bitperiod)
        factor *= 2

      # 4) we're now at midway into STOP, check whether framing was correct
      frameIsValid = (c.getValue() == 1)
      # 5) advance to the end of stop
      c.advance(bitperiod / 2)

      if omitInvalidFrames and not frameIsValid:
        # don't do unnecessary work
        continue

      # combine into a single result and return this result
      yield (eventStartsAt, data, frameIsValid)
      
    except ChannelCursorOutOfRangeException as exc:
      # this exception is expected at the end. easier to implement "out of data"
      # using an exception than handling return codes. a generator chain could
      # also be used, but let's stay with something semi-understandable
      # print("Reached end (exc)")
      # exits the top-level while, and falls through to the end with implicit
      # return (terminates the generator)
      break

if __name__ == '__main__':

  import argparse

  epilog = """
Example command line:
  UART_TX 3000000

One possible data input that will match with the example command line:
  Time[s], TRACE_A, TRACE_B, UART_TX
  0.000000000000000, 0, 0, 1
  0.362296294000000, 0, 0, 0
  0.362297918000000, 0, 0, 1
  0.362298600000000, 0, 0, 0
  0.362299226000000, 0, 0, 1
  0.362299898000000, 0, 0, 0
  0.362299902000000, 0, 0, 1
  0.362299908000000, 0, 0, 0
  0.362301534000000, 0, 0, 1
  ...
"""

  description = "Convert captured event-based CSV into UART recognized values"

  optParser = argparse.ArgumentParser(description=description, epilog=epilog,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
  optParser.add_argument('channame', type=str,
                         help="Which channel of the input data contains the UART data")
  optParser.add_argument('baudrate', type=int,
                         help="Baudrate to run recognizer with")
  optParser.add_argument('infile', nargs='?', type=argparse.FileType('r'),
                         default=sys.stdin,
                         help="File to read from (if not stdin)")
  optParser.add_argument('outfile', nargs='?', type=argparse.FileType('w'),
                         default=sys.stdout,
                         help="File to write to (if not stdout)")
  optParser.add_argument('-b', '--bits', type=int, default=8,
                         help="Data bits per frame (default: 8)")
  optParser.add_argument('-a', '--all', action='store_true',
                         help="Also emit frames that seem invalid")
  args = optParser.parse_args()

  # in column order
  channels, decimals = parseSaleaeCSV(args.infile)
  # find the channel that contains the data that we're interested in
  channel = list(filter(lambda x: x.name == args.channame, channels))
  #print(channel)
  if len(channel) != 1:
    print("Failed to locate channel %s. Available channels: %s" % (
      args.channame, ", ".join([x.name for x in channels]) ),
      file=sys.stderr)
    sys.exit(1)
  channel = channel[0]

  # emit csv header
  print("timestamp(s),byte,isFrameValid,subascii", file=args.outfile)

  # define the list of data that we emit as subascii (we don't want to confuse
  # the csv parser, nor multibyte-decoders, ie, stay in ASCII space and restrict
  # it even further)
  acceptable = string.ascii_letters + string.digits + ".+-!$:_ "

  # parse and emit bytes as they're recognized (should work even with large
  # datasets with acceptable performance)
  for ts, data, isValid in recognizeUART(channel, args.baudrate, args.bits, not args.all):
    printable = '%c' % data
    if printable not in acceptable:
      printable = ''
    frameValidDigit=0
    if isValid:
      frameValidDigit=1
    print("%.*f,%u,%u,%s" % (
      decimals,
      ts,
      data,
      frameValidDigit,
      printable), file=args.outfile)
