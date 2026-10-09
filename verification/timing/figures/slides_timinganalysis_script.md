# Timing analysis: speaker script and reference notes

Deck: `verification/timing/figures/slides_timinganalysis.pdf` (Purpose · Pipeline · Methods · Results · Limits/testbenches).
The slides carry the headings; this file carries what you say and the evidence behind it.

For each slide:
- **Script**: what to say (about 45-75 s), adding what the slide doesn't show.
- **Reference**: detailed bullets for your own understanding.
- **Q&A / stretch**: likely questions, and deeper answers if you're asked to go further.

Stress testing gets its own expanded section at the end (the liaison's focus).

---

## Slide 1: Purpose

### Script
> "We're replacing tProc with RISC-Q and keeping the signal generator. So the replacement is correct if it hands the
> generator the same commands, at the same moments, in the same order. We pinned that down with three measurements.
> Acceptance time is how quickly the controller takes a command from the program, and what it does when it can't take
> any more. Start time is when the controller actually lets a command go, compared with the time the program asked for.
> And order is whether pulses come out in the sequence we expect.
> These have to be measured, not read from the design. A command passes through three separate clocks, the processor's,
> the timeline's and the generator's, running at different speeds. Every time it crosses from one clock to another, it
> has to wait for the next clock edge, and that wait depends on how the two clocks happen to line up at that moment.
> That's clock-phase jitter. Add the queues in between, and the only reliable way to know the timing is to watch real
> commands go through and measure it."

### Reference
- **Why SGv6 matters:** only tProc is replaced. If the adapter delivers identical commands at identical times at the
  handover point, SGv6 produces identical output because it's the same hardware. So verification focuses on the
  path up to the handover (E0i → E2); the SGv6 side is used only as a final pass check.
- **The three questions**, each answered by one gap between checkpoints:
  - acceptance → E0 − E0i
  - start time → E2 − due
  - order → sequence of tags at each checkpoint
- **Why measurement:** tProc's core runs at 200 MHz (5 ns), its timeline at 430 MHz (2.324 ns per tick), and SGv6
  at 599 MHz (1.669 ns, 16 samples per cycle). Crossing between unrelated clocks gives a delay that shifts by up
  to a cycle depending on phase, which can't be computed by hand.

### Q&A / stretch
- **"Why not just compare waveforms at the DAC?"** A waveform match tells you something is wrong, not where. Timing
  checkpoints localize a difference to acceptance, release or downstream. And since SGv6 is kept, the release is the
  point the adapter actually controls.
- **"Is equivalence the right goal, or could RISC-Q be better?"** For a drop-in replacement, equivalence is the
  safe definition: existing QICK programs keep working unchanged. Improvements such as lower latency can be judged
  separately once equivalence holds.

---

## Slide 2: Pipeline

### Script
> "Here's one command's path through each controller, with our four checkpoints marked. E0i is the program writing
> the command. E0 is the controller accepting it and attaching its due time. E1 is the command reaching the part that
> watches the clock. And E2 is the release. Everything before E2 is what gets replaced; after E2 is the hardware we keep.
> Both controllers pass through the same four checkpoints in the same order, which is what makes them comparable.
> The key difference is at E2. tProc releases every command exactly four clock ticks after its due time, about
> 9 nanoseconds, because it waits until the time has *passed* the due time and then takes three clock steps to send it.
> RISC-Q does the opposite: it releases each parameter early, up to 52 cycles before the due time, so that its own
> generator lands exactly on time. Since we're keeping SGv6, the adapter has to turn that into tProc's 'four ticks after'.
> What we actually measure are the gaps between these checkpoints, and that's the next slide."

### Reference
- **Detailed walkthrough (if you want to narrate it):** In QICK, E0i is the moment the program writes the command.
  E0 is when tProc accepts it into its queue and stamps its due time. E1 is when that entry becomes visible on the
  timeline side, where the clock is watched. E2 is when the comparator lets it go, once time has passed the due time.
  In RISC-Q, E0i is the CPU's write, E0 is the fire command being decoded, E1 is the parameters entering the timed
  queues with their start time, and E2 is their release.
- **Where the checkpoints sit on each pipeline:**

  | | QICK (tProc) | RISC-Q |
  |---|---|---|
  | **E0i** | core writes to the output port | CPU store to the fire register |
  | **E0** | pushed into the wave FIFO, **due stamped** | fire decoded by the parameter buffer |
  | **E1** | FIFO entry visible on the timeline side | pushed into the timed queues, **due stamped** |
  | **E2** | comparator releases (handover to CDC) | queues release |

  Same order, same meaning at E0i and E2. The one structural difference is where the due time gets attached (E0 vs. E1).
- **Due time** = the program's relative time + tProc's reference time, attached when the command enters the queue (E0).
  Programs never see absolute time.
- **Why exactly +4 ticks:** time passes due (strict `>`) → one register copies the time → one register stores the
  compare result (the pop fires this cycle) → one register drives `tvalid`. Measured +4 on **322 of 322** on-time
  commands, with zero variation.
- **Queue behavior:** one FIFO per output port. Only the head is compared, so release is in write order.
  Depth is 256 in our emulator build and **512 on real firmware** (`FIFO_DEPTH=9` in the r23 and spinQICK r25 `.hwh`).
- **SGv6:** plays each command for `nsamp` cycles (16 samples each). If busy, the next command waits in SGv6's own
  16-deep FIFO and chains with no gap.
- **RISC-Q path:**
  - posted store → 4 pipeline registers (4 cycles) → buffer decodes the fire → 2 cycles later pushed into **six**
    per-parameter queues, each stamped with `startTime`
  - pops happen early by each parameter's pipeline depth: freqP −52, freqC −36, phase −35, amp −34, addr −11, dur −2
  - queue capacity is **5** (4 FIFO entries plus the head register)
- **Handover point:** E2 = tProc's output port into the CDC. The adapter plugs in there.

### Q&A / stretch
- **"Why does RISC-Q release early?"** Its generator has different pipeline depths per parameter. Releasing each one
  early by that depth makes every parameter arrive at the output in the same cycle, on due. It's a clean design for its own
  generator, but SGv6 expects commands at due + 4 and plays immediately.
- **"What's the end-to-end latency?"** Sent as soon as possible, tProc goes from program write to output in about
  **64 ns**: 5 ns to accept, 20 ns total to release, then about 44 ns through the kept CDC and SGv6. Native
  RISC-Q reaches release in 9 cycles. With SGv6 kept, the new system will be RISC-Q's write-to-release plus the
  adapter's own delay plus the same ~44 ns downstream.
- **"What's the ~32 cycles I've heard?"** That's QICK's *due → output* offset expressed in SGv6 cycles (~53 ns): 9.3 ns
  from tProc's release rule plus ~44 ns in SGv6. It isn't command-to-output, and most of it is kept hardware.

---

## Slide 3: Methods

### Script
> "Each gap answers one question. Write to accepted, E0i to E0, is the acceptance time. Due time to release, E2 minus
> due, is the start time, and that's the number the adapter has to match. And the order of commands across the
> checkpoints tells us whether anything was reordered.
> To measure those gaps, we ran normal QICK programs, written with its Python API, in QICKEmu, a simulation of the real
> QICK hardware design. We put a monitor at each checkpoint that writes one line for every command that passes: when
> it passed, the clock count, and the command itself. Each pulse gets a unique amplitude as a tag, so a script can follow
> it through every checkpoint, compute the gaps, and catch anything lost, duplicated or out of order.
> Before trusting the numbers, we checked them: we predicted the four-tick release from the design, and the logs showed
> exactly four; reruns gave identical logs; and shifting the clock alignment four ways didn't move the release at all.
> For RISC-Q, we translated the same tests into RISC-Q programs and logged them the same way, so both sides go through
> identical analysis."

### Reference
- **Detailed explanation (if asked to expand):**
  - **The gaps:** E0i → E0 is acceptance; due − E1 is how much margin the command had before it was due; E2 − due is
    the start-time decision the adapter must reproduce; order comes from the tag sequence at each checkpoint.
  - **How we got them:** normal QICK programs (Python API) run in QICKEmu, a simulation of the actual QICK hardware design.
    A small monitor at each checkpoint writes one line per command (time, clock count, command). Each pulse carries a
    unique amplitude as a name tag, so a script follows the same command through every checkpoint, computes every gap,
    and notices at once if a command goes missing, appears twice or comes out of order.
  - **Why the logs can be trusted:** the +4 was predicted from the design before it was measured; logged times line up
    with the real waveform; reruns give identical logs; shifting the clock alignment four ways didn't move the release
    by a single tick.
  - **RISC-Q:** each QICK test was translated directly into a RISC-Q program, run in RISC-Q's own simulation with the real
    CPU executing it, and logged in the same format. RISC-Q's real start-up sequences (normal boot, abort and restart,
    power-up) were also run.
- **Why logs instead of waveforms:** every delay becomes a subtraction in a script, reproducible and checkable over
  hundreds of commands. Waveforms were used only to confirm the monitors (`runs/test_sim/d0_trace/wave_2_release.png`).
- **Units:** E2 − due uses the timeline counter value logged at E2 and the due time logged at E0. Both are in ticks,
  so the result is an exact integer with no conversion. Cross-clock intervals use ps.
- **Validation steps, with evidence:**
  - RTL prediction +4 → measured +4
  - release spacing predicted 3 → measured 4. The difference is explained by the emulator's FIFO refill, not ignored
  - clock-phase sweep (start delay 0/13/37/71 ns): release spread 0; generator-crossing spread 1.28 ns (< 1 SGv6 cycle)
  - adding the monitors changed none of QICK's existing outputs; renaming checkpoints changed no number
- **Measurement pitfalls found and corrected** (shows rigor if asked):
  - E1 fires on every queue refill in the emulator, so only true arrivals are counted
  - a first RISC-Q analysis falsely flagged parameter mix-ups; it was re-done from per-queue logs and the flags disappeared
- **RISC-Q comparison unit:** its simulated clock has no real frequency, so results are stated in cycles of
  16 samples (1 SGv6 cycle = 1 RISC-Q batch), never in ns.
- **Scale:** QICK suite: 15+ scenario runs; RISC-Q: 17 probes. Each full suite reruns in about 2 minutes.

### Q&A / stretch
- **"Are these hardware numbers?"** They come from simulating the real RTL. tProc's rules (+4, write order,
  pause-not-drop) come from its own logic, so they should hold on hardware. The crossing delays pass through emulator
  models (simplified FIFOs), so treat those as approximate.
- **"Why not Vivado?"** Verilator is fast and scriptable, and RISC-Q simulates with it too. A single Vivado or board run
  later would calibrate the emulator-dependent numbers.
- **"Which firmware does the emulator match?"** The r23 standard build: SGv6 at 599 MHz, unrelated to tProc's clock.
  The spinQICK r25 build runs SGv6 on tProc's 430 MHz clock, so its crossing should be deterministic. That needs a
  separate build profile.

---

## Slide 4: Results

### Script
> "Three findings. First, start time is exact: across single pulses, three spacings and four clock alignments,
> tProc released every command four ticks after its due time, 322 out of 322, with zero variation. That means it
> can be checked with equality, not a tolerance.
> Second, acceptance is where the two differ most. To see what happens when a controller's queue fills up, we
> scheduled more pulses than the queue can hold. tProc handled it by pausing the program until space freed up. It
> waited about 7 microseconds, and every pulse still went out. RISC-Q's queues hold only about five commands, and when
> they're full new ones are simply dropped. With eight scheduled, three disappeared, and neither the CPU nor anything
> else noticed. We also had a program write a pulse after its due time had already passed: both controllers sent it
> immediately, and neither flagged that it was late.
> Third, order matches. When a later pulse is written before an earlier one, both controllers keep write order: the
> earlier pulse waits its turn, 223 ticks in our test. And pulses on two outputs with the same due time left in the
> same cycle on both.
> Notice that each of these results is really a rule: release at due plus four; accept, or pause, but never drop;
> release in write order. Rules like that can be checked automatically, and that's how we turn this study into a
> testbench."

### Reference
- **Start time:**
  - T1–T3 (gaps 0.3/0.5/0.7 µs) and T7 (4 clock phases): release − due = +4 always
  - once released, SGv6 starts 37.7–39.3 ns after due (jitter < 1 SGv6 cycle, from the clock crossing) and the
    output follows 9 cycles later. That's kept hardware, used as the pass check
- **Acceptance:**
  - T9a: 300 pulses due 10 µs onward. 256 accepted in 3.8 µs; core halted 7.11 µs until the first release; 45 pause
    intervals (8.6 µs total); release stayed exactly +4 throughout; 300/300 delivered
  - TRM confirms: pause-when-full is the default, with a config bit ("DISABLE FIFO_FULL_PAUSE") to turn it off
  - RISC-Q P6: 4 and 5 pending fine; 8 pending → pulses 6–8 dropped in all six queues (so parameters didn't
    desynchronize; the whole command vanished)
- **Late command:**
  - tProc T8: the program waited until 1.0 µs, then wrote a pulse due at 0.8 µs (92 ticks late). It was released 20.4 ns
    after the write, with no flag
  - RISC-Q P5: released 9 cycles after the write, no flag
- **Order:**
  - T6 / P4: a pulse due at 1.0 µs written before one due at 0.5 µs → the 0.5 µs pulse was released at +223 ticks,
    behind the other, on both
  - P4 variant: each pulse kept its own frequency through the separate frequency queues
- **Outputs together:** T10 / P7: same due on two outputs → same cycle (skew 0) on both.

### Q&A / stretch
- **"Is 256 vs 512 a problem?"** No. The rule (pause, never drop) is the same; only the depth differs by build.
  The real firmware holds 512.
- **"Why does RISC-Q drop instead of pausing?"** Its CPU writes are 'posted': acknowledged immediately and sent down a
  one-way link with no backpressure path, and the queues accept only when not full. That's efficient, but a full queue
  has no way to tell the CPU to wait.
- **"Is order a risk then?"** Not a difference between the two, but a responsibility: both rely on the program writing
  commands in time order. A compiler or adapter that reorders commands would break it on both.
- **"What about native RISC-Q's generator?"** Its own generator cuts overlapping pulses short and starts late pulses with
  stale settings, but those behaviors disappear if SGv6 is kept. They only matter if someone proposes replacing SGv6.

---

## Slide 5: Limits, start-up and testbenches

### Script
> "Here's how those rules become a testbench. From each tProc run we keep the rules with their limits, and the recorded
> release stream: which command left at which tick. That recording is the expected output. A candidate, the adapter or
> RISC-Q, runs the same program, and a checker compares its release stream against it. For example, tProc released our
> two test pulses at ticks 649 and 864. A candidate that releases the second one at 861 fails: three ticks early.
>
> On top of that, we stress the controllers. What we've already run: overfilling the queue, which is where tProc pauses
> and RISC-Q drops; writing a pulse after its due time; writing pulses out of order; and firing several outputs at once,
> which lined up exactly on both.
> Still to come are the stresses that look most like real experiments. Real QICK programs run shot by shot and only
> stay a little ahead of the clock. The first is slack erosion: giving the program enough work between pulses that it
> starts falling behind the clock, and checking that every late pulse is caught, since neither controller flags it
> today. The second is feedback, where a pulse can only be sent after a measurement result comes back; there the
> controller's own delay adds directly to the loop time. The third is long runs: RISC-Q's 32-bit clock wraps every few
> seconds, and our simulations never reached that point. The fourth is restart and power-up. On RISC-Q we've already
> seen pulses from an aborted run still play after a restart, so this needs to be tested across repeated runs.
>
> One side note: some checks don't need a reference at all, because they protect the hardware we're keeping. For
> example, the signal generator assumes every pulse is at least three cycles long. A length of 0 or 1 plays for about
> 109 microseconds. QICK's compiler prevents that today, but with RISC-Q in the loop the adapter has to."

### Reference
- **Golden reference = expected output**, in two forms:
  - rules with limits (`verification/timing/tables/contract.csv`): e.g. release − due == 4, SGv6 start band
  - recorded release streams (`runs/<test>/d0/ev_e2_tproc_out.csv`): exact command + tick per scenario
- **Two kinds of checks:**
  - **equivalence:** same as tProc? (release tick, order, fields; needs the tProc recording)
  - **legality:** safe for the kept hardware? (always on, no reference needed): nsamp ≥ 3, never release early,
    command held stable until accepted, no generator backlog
- **Staged testing:**
  - Stage 0 (now): inject errors into a recorded stream to prove the checker catches them; replay tProc's stream into
    SGv6 to prove the handover decides the output
  - Stage 1: RISC-Q alone (order, capacity, lateness, restart)
  - Stage 2: adapter pieces (command format, handshake)
  - Stage 3: full adapter (release stream == tProc's; output == tProc's)
- **Limits, with evidence:**
  - **F1 tProc overload** (T9b, 300 pulses due at once): once the downstream FIFO fills, tProc changes the command it's
    offering while waiting → 4 lost, 3 duplicated, 1 all-zero command. Confirmed on a traced waveform. It's in tProc's
    own RTL
  - **F8 shared crossing FIFO** (T11): SG0 overloaded; SG1 was sent 2 commands but accepted 656 and started 640. It's
    upstream QICK logic, present in the r23 firmware (one block feeds all 4 SGv6); the spinQICK r25 build has none on the pulse path
  - **F9 pulse length:** SGv6's counter leaves a pulse when it reaches 2, so length 0/1 wraps: 65,536 cycles = 109.4 µs
    (measured); 2 and 3 are exact. QICK's compiler enforces ≥ 3
- **Start-up (RISC-Q only so far):**
  - abort + rerun: pulses scheduled before the abort still played (4 pulses for 2 planned), because RISC-Q's reset
    doesn't reach its queues
  - power-up: 2 stray pulses before the software took control
  - tProc's TRM says its reset flushes the FIFOs

### Q&A / stretch
- **"Is the shared-FIFO behavior a bug?"** Strictly it breaks the streaming protocol, but it only appears when a generator
  backs up, which takes a sustained scheduling error that QICK's compiler warns about. The real risk is an adapter that
  pushes commands early into SGv6 to make up for RISC-Q's small queues; that would trigger it on every generator.
  Rule: never release early; SGv6 isn't a buffer.
- **"Why does the testbench need a 'build profile'?"** Queue depth (256 vs 512) and clocking (r23 unrelated vs r25
  related) differ between builds; the checks read them from a profile instead of hard-coding emulator values.
- **"How fast can we run it?"** The whole QICK suite and the RISC-Q suite each take about 2 minutes.

---

## Stress testing (expanded, for the liaison)

### Opening line
> "Stress testing only means something if it matches how QICK is really used, so we first looked at how QICK programs
> run, then chose stresses that push on the realistic limits."

### The key fact that shapes stress tests
- QICK's standard program class runs the body as a **shot** inside a repeat loop, and **ends every shot by pausing the
  processor until that shot's readouts finish** (`wait_auto`, then the relaxation delay). Source: `qick_lib/qick/asm_v2.py:2822-2834`.
- Consequence: the controller's queue only ever holds **one shot's commands**. The meaningful capacity question is
  **"how many pulses does one shot schedule per channel?"**, not "how many in the whole experiment".
- QICK's own docs call the program's lead over the timeline **"slack"**, and warn that without it "future timed
  instructions will pile up" (`asm_v2.py:1466-1472`). Running out of slack is QICK's recognized timing failure.

### Stress tests completed

| Stress | Evidence | What it established |
|---|---|---|
| Capacity: 300 queued (T9a / P6) | tProc 300/300, 7.1 µs pause · RISC-Q 5 kept, 3 of 8 dropped | pause-not-drop vs silent drop |
| Late command (T8 / P5) | released 20 ns / 9 cycles after write, no flag | lateness is silent on both |
| Order scrambled (T6 / P4) | earlier pulse waited 223 ticks on both | write order is the rule |
| Outputs together (T10 / P7) | skew 0 on both | multi-output alignment holds |
| Clock alignment ×4 (T7) | release spread 0; crossing spread 1.28 ns | jitter bounded below one SGv6 cycle |
| Overload (T9b) | 4 lost, 3 dup, 1 zero command | the reference stops at downstream overload (F1) |
| One generator backed up (T11) | other generator: 2 sent → 656 accepted | shared FIFO corrupts neighbors (F8) |
| Pulse length edge (0/1/2/3) | 0/1 → 109.4 µs; 2/3 exact | SGv6 needs ≥ 2; compiler enforces ≥ 3 (F9) |
| RISC-Q abort + rerun (P8) | 4 pulses for 2 planned | reset doesn't clear scheduled pulses |
| RISC-Q power-up (P9) | 2 stray pulses, 8 dropped writes | output before software takes control |

### Stress tests planned (realistic)

| # | Stress | Real-experiment situation | Measure | Pass if |
|---|---|---|---|---|
| S1 | pulses per shot, swept 1 → ~20 on one channel | pulse trains, multi-pulse shots (first demo already uses 5) | commands lost/duplicated at E2 | every pulse released once at due + 4 |
| S2 | slack erosion: add work between pulses (register updates, subroutines like the demo's virtual-Z) and shorten spacing | fast sweeps, heavy per-shot computation | lead margin at E1; any release later than due + 4 | lateness detected and reported, never silent |
| S3 | feedback latency: pulse issued after a readout decision (demo `FeedbackProgram`, HMC feedback notebook) | active reset, conditional gates | write → release (E0i → E2) for the decided pulse | adapter adds a known, bounded delay |
| S4 | one generator busy while others play (extends T11) | simultaneous drive on several qubits, drive + readout | every generator's command count and timing | no generator affected by another's load |
| S5 | repeated rounds and interrupted rounds (demos use `rounds=10`) | every normal acquisition restarts the processor per round | leftover or stray pulses at the start of the next round | clean start every round |
| S6 | long runs: start RISC-Q's time near its 32-bit wrap (host time-offset register) | experiments running minutes to hours; RISC-Q's counter wraps every few seconds (≈7 s at ~600 MHz; clock TBD) | releases scheduled across the wrap | correct release across wrap |

### Why this set (talking points)
- **S1** turns RISC-Q's 5-deep queue from a number into a threshold: the point where ordinary programs start losing pulses.
- **S2 and S3** target the failure QICK itself warns about (running out of slack) and the one case where real programs
  are late by design (feedback). Both matter because **lateness is silent on both controllers**, so the testbench
  must detect it.
- **S4 and S5** come directly from our findings (F8, reset behavior) and model normal multi-qubit use and normal repeated
  acquisition.
- **S6** is RISC-Q-specific. Its own source notes that simulations starting at time 0 never test the wrap region.
  tProc's 48-bit counter would take days to wrap.

### Deliberately deprioritized
- **300 due at once:** not a real workload; kept once, as the overload boundary.
- **Absolute time jumps (`TIME updt`):** QICK's standard library only moves the reference time, never absolute time.
- **Power-up:** real, but it happens before any experiment; one test is enough.

### Q&A / stretch
- **"Is 300 queued realistic?"** No. Programs pause after every shot, so the queue holds one shot. It was the right
  probe to prove "pause, never drop", and it's how we found the overload defect.
- **"What's the most realistic worst case?"** A dense shot on one channel (S1) combined with per-pulse computation (S2):
  that's where RISC-Q's small queues and silent lateness would show up first.
- **"Can these run before the adapter exists?"** Yes. S1, S2, S5 and S6 run on RISC-Q alone with the existing logger and
  analysis; S3 and S4 run on QICK now to set the reference.
- **"What pass criteria do stress tests use?"** The same checker: equivalence (due + 4, order, once each) plus legality
  (length ≥ 3, never early, no backlog). A stress test passes when no rule fires, not when a number "looks fine".
