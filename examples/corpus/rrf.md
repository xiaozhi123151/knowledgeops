# Reciprocal Rank Fusion

RRF merges ranked lists with score sum(1/(k+rank)). KnowledgeOps uses k=60. RRF does not directly add incompatible dense and BM25 raw scores.

RRF 倒数排名融合使用排名而非直接相加原始得分，常数 k 默认等于 60。