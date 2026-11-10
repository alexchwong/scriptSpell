# Rolling averages

## Task

Compute rolling means over integers for a positive window size. Emit null before the first full window, then exact fractions with window sum as numerator and window size as denominator.

## Medium guidance

Track the sum of the active window. Return a fraction object for every full window.

## Easy guidance

Add each new value and subtract the value that falls out of the window. Cover a nonintegral mean and a window longer than the input.
