# generate-call-sequence

This program takes an event-based CSV file as an input, a specification on how
these events translate into calls/returns/marks (and context switches if any)
and produces an JSON formatted output suitable for consumption in Chrome's
trace event viewer (about:tracing).

Canonical URL for project:
https://github.com/majava3000/slib-tools/tree/master/generate-call-sequence

# Limitations & future work

The trace format does not directly support blocking/asynchronous contexts, since
it's more geared towards viewing trace data in modern multi-threaded /
multi-threaded browser environments. However, an additional "async" track is
created by this tool to indicate asynchronous contexts (which can nest).

The output is structured so that the selecting an "area" in the viewer will
still calculate total time and "self time" correctly, as well as function
counts. Keeping this function restricts possible visualization methods that
otherwise might've been more clear.

This tool is not able to fix accuracy of the timestamps (ie, if your emitting
path adds non-determenistic latency, there's nothing that this tool can do to
fix that). Please see the `README.md` in `decode-serial` for a possible future
fix.

Should be fixed first:

* Event stream that starts midway of a "call stack" will cause incorrect output
  since events that start and complete before this is identified are emitted
  from the default context, while the terminating ones are discarded.
* Set a sane max nesting level (allow to override on command line). Now there's
  no limit.
* Current logic buffers events unnecessarily. Possible to convert into a pure
  filter with low effort (sort and emit when stack empties, keeping buffering
  to minimum).
* Allow termination upon implicit unwinds and empty-stack unwinds. Now both
  generate warnings but processing always continues.
* Allow custom colors (use HSV triangle-division based automatic allocation to
  make colors distinct based on rarity or closeness). Although all of the
  fancier allocation policies will require full analysis before emit (requiring
  full buffering). Need to figure out how on earth custom colors are possible
  first (experiments so far yielded parsing errors in Chrome).

Development ideas:

* Identify unique call sequence stacks in stream, and only emit them (with
  counts for each). Useful for longer period captures where system operation is
  not completely periodic.
  * Extend the model also to track percentiles of durations, so that for each
    unique sequence, we can get the variance in execution times across the input
    data set.
* Allow context switch based on auxiliary signal tracks (via GPIO), or perhaps
  use the async event track for system state related information (need new type
  of spec entry for this). Think power management states (which might not need
  GPIO, but it would be quite useful due to low latency impacts)
* Consider other output formats (plantuml perhaps, and graphviz state transition
  probability output).

# Use cases and examples

Currently input data formats (for the CSV and event specification) are not
documented directly, but hopefully the files under `testdata/` might be of use
as well as the article covering the use cases of this tool in [this article](https://lowerstrata.net/post/serial-tracing/).

Pro-tip: to pretty-print the generated JSON, use `python -m tool.json < events.json`

# Dependencies

The program should run equally in python 2 and python 3 environments and has no
dependencies outside the python standard library. The program should also run
equally well in non-UNIX environments, although main development is done on a
Linux desktop.

# Contributing

Contributions are appreciated, please use the canonical project URL for issues
and pull-requests. This tool is released under the GPLv3 license (please see the
included `LICENSE` file for details). Contributions do not require a CLA.
