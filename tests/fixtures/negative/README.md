# Negative fixtures

Everything here is **deliberately broken**. Each file breaks exactly one gate,
so `runtime-negative.yml` can prove that gate still fails on bad input.

Do not fix these. A green run of a negative lane is the defect.

The positive fixtures live one directory up and are the opposite: each is
deliberately clean, so a failure there is a real one.
