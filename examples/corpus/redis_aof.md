# Redis AOF

AOF (Append Only File) records Redis write commands. The appendfsync everysec policy can lose about one second of writes after a crash. AOF rewrite compacts the log.

Redis 的 AOF 追加日志记录写命令。每秒刷盘策略在崩溃时可能丢失约一秒写入，重写用于压缩日志。