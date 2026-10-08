"""
STM32 Timer PWM Solver
------------------------------------------------------------
Given a timer clock frequency and a target PWM frequency (or period),
this script finds the Prescaler (PSC) and Auto-Reload (ARR) register
values for an STM32 timer.

Counting modes:
    Edge-aligned (Up or Down count):
        Fpwm = Fclk / ( (PSC+1) * (ARR+1) )

    Center-aligned (dual-slope, CMS mode):
        Fpwm = Fclk / ( 2 * (PSC+1) * (ARR+1) )
        (the counter goes up AND down each period, doubling the divider)

You pick the mode at runtime, and the search automatically accounts
for the factor of 2 in center-aligned mode.

Speed:
Instead of a brute-force double loop over PSC and ARR (~4.3 billion
combinations), this uses NumPy to vectorize the search. For every
candidate PR = PSC+1, the best matching AR = ARR+1 is computed
directly:

    AR = round(Fclk_eff / (Ftarget * PR))

This drops the complexity from O(n^2) down to O(n): the full search
over all 65534 values runs in a few milliseconds.

Smart input parsing:
The PWM target can be typed as either a frequency or a time (period),
with an optional SI prefix. The output is then shown in the SAME kind
of unit you typed in (frequency in / frequency out, time in / time
out), so if you type a period you get periods back, not Hz.

    Suffix 'f' -> frequency (Hz)
    Suffix 's' -> time / period (seconds)

    SI prefixes (case-sensitive):
        p -> 1e-12   (pico)
        n -> 1e-9    (nano)
        u -> 1e-6    (micro)
        m -> 1e-3    (milli)   [lowercase only]
        k or K -> 1e3   (kilo)
        M -> 1e6     (mega)    [uppercase only]
        G -> 1e9     (giga)

    Examples:
        50f      -> 50 Hz
        20e-3s   -> 0.02 s
        20us     -> 20 microseconds
        20ms     -> 20 milliseconds
        10Kf     -> 10 kHz
        10Mf     -> 10 MHz

    A plain number with no suffix (e.g. "72000000") is treated as a
    frequency in Hz directly, for backward compatibility.

Extra candidates:
After the main result table, the script offers to list ALL other
candidates that fall within the error threshold, sorted by error
(smallest first, then largest PR first), printed in one table.
"""

import re
import numpy as np

MAX_VAL = 65535  # PSC+1 and ARR+1 are each 16-bit: valid range 1..65534

PREFIX_MULTIPLIERS = {
    "": 1.0,
    "p": 1e-12,
    "n": 1e-9,
    "u": 1e-6,
    "m": 1e-3,
    "k": 1e3,
    "K": 1e3,
    "M": 1e6,
    "G": 1e9,
}

# number, optional SI prefix, optional unit letter (f/F = frequency, s/S = time)
_VALUE_RE = re.compile(
    r"^\s*([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s*([pnumkKMG]?)\s*([fFsS]?)\s*$"
)


def parse_input(raw: str):
    """
    Parse a user-typed frequency/time string.
    Returns (hz_value, mode) where mode is 'freq' or 'time' depending
    on which unit the user actually typed (no unit defaults to 'freq').
    """
    match = _VALUE_RE.match(raw)
    if not match:
        raise ValueError(
            f"Could not parse '{raw}'. Examples: 50f, 20e-3s, 20us, 10Kf, 10Mf"
        )

    number_str, prefix, unit = match.groups()
    number = float(number_str)

    if prefix not in PREFIX_MULTIPLIERS:
        raise ValueError(f"Unknown SI prefix '{prefix}' in '{raw}'")

    value = number * PREFIX_MULTIPLIERS[prefix]
    unit = unit.lower()

    if unit == "s":
        if value == 0:
            raise ValueError("Time value cannot be zero")
        return 1.0 / value, "time"   # period -> frequency, remember it was a period
    else:
        # unit == "f" or no unit given -> already a frequency in Hz
        return value, "freq"


def prompt_value(label: str):
    while True:
        raw = input(f"{label}: ").strip()
        try:
            return parse_input(raw)
        except ValueError as e:
            print(f"  {e}\n  Please try again.")


def prompt_alignment_mode():
    while True:
        raw = input(
            "Counting mode - (e)dge-aligned Up/Down or (c)enter-aligned [e/c]: "
        ).strip().lower()
        if raw in ("e", "edge", "u", "up", "d", "down", "up/down", "updown"):
            return 1, "Edge-aligned (Up/Down count)"
        if raw in ("c", "center", "centre", "center-aligned"):
            return 2, "Center-aligned (dual-slope)"
        print("  Please enter 'e' for edge-aligned or 'c' for center-aligned.")


def find_pwm_settings(Fclk: float, Ftarget: float, factor: int):
    """
    factor = 1 for edge-aligned, 2 for center-aligned.
    Internally we just search against an effective clock of Fclk/factor,
    since Fpwm = Fclk / (factor * PR * AR).

    Returns: best, pr_max, ar_max, Fdelta, count, candidates
    where `candidates` is a list of result dicts (PR/AR/FCalc/diff) for
    every entry within the threshold, sorted by error then by PR (desc).
    """
    Fclk_eff = Fclk / factor

    pr = np.arange(1, MAX_VAL, dtype=np.float64)          # PR = PSC+1, [1 .. 65534]

    ar_ideal = Fclk_eff / (Ftarget * pr)
    ar = np.round(ar_ideal)
    ar = np.clip(ar, 1, MAX_VAL - 1)

    fcalc = Fclk_eff / (pr * ar)
    fdiff = np.abs(fcalc - Ftarget)

    pr_int = pr.astype(np.uint32)
    ar_int = ar.astype(np.uint32)

    # ---- overall best match (smallest frequency error) ----
    best_idx = np.argmin(fdiff)
    best = {
        "PR": int(pr_int[best_idx]),
        "AR": int(ar_int[best_idx]),
        "FCalc": float(fcalc[best_idx]),
        "diff": float(fdiff[best_idx]),
    }

    # ---- largest PR / largest AR within an error threshold ----
    Fdelta = 1e-8
    mask = fdiff < Fdelta
    while not np.any(mask):
        Fdelta *= 10
        mask = fdiff < Fdelta

    valid_pr = pr_int[mask]
    valid_ar = ar_int[mask]
    valid_fcalc = fcalc[mask]
    valid_fdiff = fdiff[mask]

    pr_max_i = np.argmax(valid_pr)
    ar_max_i = np.argmax(valid_ar)

    pr_max = {
        "PR": int(valid_pr[pr_max_i]),
        "AR": int(valid_ar[pr_max_i]),
        "FCalc": float(valid_fcalc[pr_max_i]),
        "diff": float(valid_fdiff[pr_max_i]),
    }
    ar_max = {
        "PR": int(valid_pr[ar_max_i]),
        "AR": int(valid_ar[ar_max_i]),
        "FCalc": float(valid_fcalc[ar_max_i]),
        "diff": float(valid_fdiff[ar_max_i]),
    }

    # ---- every candidate within threshold: smallest error first, then largest PR ----
    order = np.lexsort((-valid_pr.astype(np.int64), valid_fdiff))
    candidates = [
        {
            "PR": int(valid_pr[i]),
            "AR": int(valid_ar[i]),
            "FCalc": float(valid_fcalc[i]),
            "diff": float(valid_fdiff[i]),
        }
        for i in order
    ]

    return best, pr_max, ar_max, Fdelta, int(mask.sum()), candidates


def format_freq(hz: float) -> str:
    a = abs(hz)
    if a >= 1e9:
        return f"{hz/1e9:.6f} GHz"
    if a >= 1e6:
        return f"{hz/1e6:.6f} MHz"
    if a >= 1e3:
        return f"{hz/1e3:.6f} kHz"
    return f"{hz:.6f} Hz"


def format_time(sec: float) -> str:
    a = abs(sec)
    if a >= 1:
        return f"{sec:.6f} s"
    if a >= 1e-3:
        return f"{sec*1e3:.6f} ms"
    if a >= 1e-6:
        return f"{sec*1e6:.6f} us"
    if a >= 1e-9:
        return f"{sec*1e9:.6f} ns"
    return f"{sec*1e12:.6f} ps"


def print_results_table(Fclk, Ftarget, target_mode, mode_label, rows, show_header=True):
    """rows: list of (label, dict-with-PR/AR/FCalc/diff)"""
    if target_mode == "time":
        calc_header, diff_header = "Tcalc", "Diff"
    else:
        calc_header, diff_header = "Fcalc", "Diff"

    headers = ["Result", "PSC reg", "ARR reg", calc_header, diff_header, "Error (%)"]

    Ttarget = 1.0 / Ftarget if Ftarget != 0 else 0.0

    table_rows = []
    for label, r in rows:
        if target_mode == "time":
            t_calc = 1.0 / r["FCalc"] if r["FCalc"] != 0 else float("inf")
            diff_t = abs(t_calc - Ttarget)
            error_pct = (diff_t / Ttarget) * 100.0 if Ttarget != 0 else 0.0
            calc_str = format_time(t_calc)
            diff_str = format_time(diff_t)
        else:
            error_pct = (r["diff"] / Ftarget) * 100.0 if Ftarget != 0 else 0.0
            calc_str = format_freq(r["FCalc"])
            diff_str = format_freq(r["diff"])

        table_rows.append([
            label,
            str(r["PR"] - 1),   # PSC register value = PR - 1
            str(r["AR"] - 1),   # ARR register value = AR - 1
            calc_str,
            diff_str,
            f"{error_pct:.6f}",
        ])

    col_widths = [
        max(len(headers[i]), *(len(row[i]) for row in table_rows))
        for i in range(len(headers))
    ]

    def fmt_row(cells):
        return "| " + " | ".join(c.ljust(w) for c, w in zip(cells, col_widths)) + " |"

    sep = "+-" + "-+-".join("-" * w for w in col_widths) + "-+"

    if show_header:
        target_str = (
            format_time(Ttarget) if target_mode == "time" else format_freq(Ftarget)
        )
        print(f"\nMode: {mode_label}")
        print(f"Fclk = {format_freq(Fclk)}   Target = {target_str}")
    print(sep)
    print(fmt_row(headers))
    print(sep)
    for row in table_rows:
        print(fmt_row(row))
    print(sep)


def show_candidates(Fclk, Ftarget, target_mode, mode_label, candidates):
    """Print all candidates within the threshold in a single table."""
    total = len(candidates)
    print(f"\nAll candidates within threshold: {total} "
          f"(sorted by error, then largest PR first)")

    rows = [(f"#{i + 1}", r) for i, r in enumerate(candidates)]
    print_results_table(
        Fclk, Ftarget, target_mode, mode_label, rows, show_header=False
    )


def main():
    while True:
        Fclk, _clk_mode = prompt_value("Timer Clock (e.g. 72000000, 72Mf)")
        Ftarget, target_mode = prompt_value(
            "PWM Target  (e.g. 50f, 20e-3s, 20us, 10Kf)"
        )
        factor, mode_label = prompt_alignment_mode()

        best, pr_max, ar_max, used_delta, count, candidates = find_pwm_settings(
            Fclk, Ftarget, factor
        )

        print_results_table(Fclk, Ftarget, target_mode, mode_label, [
            ("Best (min error)", best),
            ("Max PR", pr_max),
            ("Max AR", ar_max),
        ])
        print(f"candidates within threshold : {count}  (Fdelta = {used_delta:.1e})")

        # ---- optional: list every other candidate ----
        if count > 1:
            more = input(
                "\nShow all other candidates too? (y/n): "
            ).strip().lower()
            if more == "y":
                show_candidates(Fclk, Ftarget, target_mode, mode_label, candidates)

        again = input("\nRun another calculation? (y/n): ").strip().lower()
        if again != "y":
            break


if __name__ == "__main__":
    main()
