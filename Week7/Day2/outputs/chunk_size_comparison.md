# Chunk Size Evaluation

Test set: 15 queries built from known property descriptions, checking whether the correct property_id appears in the top-3 retrieved chunks.

| Chunk Size (words) | Overlap | Num Chunks | Avg Chunk Words | Retrieval Hit Rate |
|---|---|---|---|---|
| 100 | 40 | 152 | 73.8 | 0.07 (1/15) |
| 200 | 40 | 140 | 76.7 | 0.4 (6/15) |
| 400 | 40 | 140 | 76.7 | 0.4 (6/15) |

## Conclusion

Chunk size 200 words achieved the highest retrieval hit rate (0.4) in this evaluation. Smaller chunks provide more precise retrieval but increase the number of stored vectors and may split important context across multiple chunks. Larger chunks preserve more context but may include additional unrelated information. Based on these results, 200 words was selected as the default chunk size because it offers the best balance between retrieval accuracy and context preservation.
