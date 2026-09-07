@echo off
REM V2.0 端到端 demo — 强制 UTF-8 输出（Windows GBK 兼容）
chcp 65001 > nul
py -3.12 scripts\demo_v20_full.py