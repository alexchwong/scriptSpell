# Rank stock levels

## Task

Return up to five products with the lowest stock, breaking ties by SKU.

Input

A list of product records, each with a SKU and a stock quantity.

Expected output

Up to five original product records ordered by increasing quantity, then by SKU. An empty inventory produces an empty list.

## Medium guidance

Sort ascending by quantity, then ascending by SKU, and take the first five.

## Easy guidance

Keep the product records intact. Cover equal stock counts and an inventory with fewer than five products.
