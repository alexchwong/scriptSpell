# Rolling averages

## Task

Compute rolling means over integers for a positive window size. Emit null before the first full window, then exact fractions with window sum as numerator and window size as denominator.

Input

An ordered list of integers and a positive integer window size.

Expected output

One entry per input value. Before the first full window use null. Thereafter return a numerator and denominator object using the window sum and window size, without reducing the fraction.

## Medium guidance

Track the sum of the active window. Return a fraction object for every full window.

## Easy guidance

Add each new value and subtract the value that falls out of the window. Cover a nonintegral mean and a window longer than the input.
