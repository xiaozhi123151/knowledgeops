# Redis RDB

RDB creates point-in-time snapshots. Data written after the last completed snapshot can be lost. RDB is useful for compact backups and fast loading.

Redis 的 RDB 保存时间点快照，最后一次快照之后的数据存在丢失风险，适合紧凑备份。