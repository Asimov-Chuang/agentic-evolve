# Manned Lunar Landing Trajectory Optimization

Design a planar Earth-Moon transfer trajectory for a crewed lunar landing mission under the circular restricted three-body problem (CR3BP). The candidate program must generate a file named `results.txt` in its current working directory. The evaluator runs the Frontier-Engineering MannedLunarLanding benchmark validator and scores the mission by validated lunar payload mass in kg.

## Objective

Maximize the payload mass delivered to lunar orbit and left on the Moon while satisfying all mission, dynamics, fuel, timing, and file-format constraints. A valid mission receives `score = payload_kg`; invalid missions receive no useful score.

## Candidate Contract

- You may modify the Python candidate program logic inside the evolvable block.
- The program must run as a standalone Python script.
- The program must write `results.txt` in the current working directory.
- Keep the expected `results.txt` filename and schema unchanged.
- Do not depend on modifying benchmark validators or Frontier-Engineering metadata.

## Physical Model

Use normalized CR3BP Earth-Moon synodic-frame dynamics:

- Earth gravitational parameter: `mu_e = 398600 km^3/s^2`
- Moon gravitational parameter: `mu_m = 4903 km^3/s^2`
- Earth radius: `R_e = 6378 km`
- Moon radius: `R_m = 1737 km`
- Distance unit: `LU = 384400 km`
- Time unit: `TU = sqrt(LU^3 / (mu_e + mu_m))`
- Velocity unit: `VU = LU / TU`

The mission starts from a circular 400 km Earth orbit, reaches a circular 100 km lunar orbit, stays at the Moon, departs lunar orbit, and returns to an Earth periapsis altitude of 0 km. Optional fuel resupply can use the benchmark's L1 Lyapunov supply spacecraft if implemented correctly.

## Mass And Fuel

The spacecraft mass is dry mass plus fuel plus lunar payload.

- Dry mass including crew: `10000 kg`
- Maximum fuel capacity: `15000 kg`
- Initial mass from launch energy: `M0 = 25000 - 1000 * C3`
- Fuel consumption for an impulse `delta_v` in m/s: `Mf = M * exp(-delta_v / 3000)`
- Payload is left on the Moon after lunar arrival/mission.
- Remaining fuel at Earth return must not exceed `100 kg`.

## Mission Constraints

- Total mission duration must be at most 100 days.
- Lunar stay duration must be between 3.0 and 10.0 days.
- Transfer trajectory must remain within 2 Earth-Moon distances.
- Moon altitude must not be below 100 km.
- Earth altitude before final return must not be below 400 km.
- Patch points and orbit endpoints must satisfy the benchmark precision tolerances.
- Fuel bookkeeping must be physically consistent and never exceed tank limits.

## `results.txt` Format

Each row has 10 columns. Column 1 is integer event code; all other columns must be scientific notation with 12 significant digits.

1. `Event`
2. `Time` in TU
3. `X` in LU
4. `Y` in LU
5. `Vx` in VU
6. `Vy` in VU
7. `dVx` in VU
8. `dVy` in VU
9. `Mfuel` in kg
10. `Mcarry` lunar payload in kg

Event codes:

- `-1`: impulsive maneuver
- `0`: coast / propagation segment
- `1`: Earth departure
- `2`: lunar orbit arrival and mission start
- `3`: lunar orbit departure and mission completion
- `4`: Earth return; this must be the last row
- `5`: optional rendezvous with the supply spacecraft

Recording rules:

- Event `0` propagation segments need at least two rows, start and end.
- Event `-1` maneuvers need two consecutive rows: pre-maneuver with zero impulse, then post-maneuver with impulse components and updated fuel.
- Events `2` and `3` must be consecutive rows with no inserted event between them.
- Event `5` resupply records need before/after rows if used.
- Event `4` must appear only as the final row.

## Feedback And Raw Artifacts

The evaluator stores raw artifacts for every attempt. Standard and pro modes can inspect archived `raw-artifact.json` sidecars. Pro mode evolves `analyzer.py`; use the analyzer to extract useful signals from `results.txt`, `outputlog.txt`, metrics, stdout, stderr, event structure, fuel traces, and validator failures without spending extra evaluation budget.
