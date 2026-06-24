#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
LOG_FILE="/tmp/github_hot_daily.log"
MLX_PID=""

cleanup() {
    if [ -n "$MLX_PID" ] && kill -0 "$MLX_PID" 2>/dev/null; then
        kill "$MLX_PID" 2>/dev/null
        echo "[$(date '+%H:%M:%S')] MLX 翻译服务已停止" | tee -a "$LOG_FILE"
    fi
}
trap cleanup EXIT

# 1) 启动 MLX 翻译服务
echo "==================================================" | tee -a "$LOG_FILE"
echo "[$(date '+%H:%M:%S')] 启动 MLX 翻译服务..." | tee -a "$LOG_FILE"
nohup mlx_lm.server --model /Users/ryan/mlx-env/models/Hy-MT2-7B-4bit --host 0.0.0.0 --port 8080 --trust-remote-code > /tmp/mlx_server.log 2>&1 &
MLX_PID=$!
echo "[$(date '+%H:%M:%S')] MLX PID: $MLX_PID" | tee -a "$LOG_FILE"

# 等待模型加载就绪
sleep 60
for i in $(seq 1 6); do
    if curl -s --max-time 30 http://localhost:8080/v1/chat/completions \
        -d '{"model":"/Users/ryan/mlx-env/models/Hy-MT2-7B-4bit","messages":[{"role":"user","content":"test"}],"stream":false}' \
        > /dev/null 2>&1; then
        echo "[$(date '+%H:%M:%S')] MLX 服务就绪" | tee -a "$LOG_FILE"
        break
    fi
    echo "[$(date '+%H:%M:%S')] 等待 MLX 服务... ($i)" | tee -a "$LOG_FILE"
    sleep 10
done

# 2) 执行 refresh
echo "[$(date '+%H:%M:%S')] 执行 refresh..." | tee -a "$LOG_FILE"
PYTHONPATH=src python -m github_hot.cli refresh 2>&1 | tee -a "$LOG_FILE"

# 3) 提交并推送
echo "[$(date '+%H:%M:%S')] 提交代码..." | tee -a "$LOG_FILE"
git add -A
git commit -m "daily refresh $(date +%Y-%m-%d): MLX translation, trend update" || echo "无变更跳过提交"
echo "[$(date '+%H:%M:%S')] 推送..." | tee -a "$LOG_FILE"
git push

echo "==================================================" | tee -a "$LOG_FILE"
echo "[$(date '+%H:%M:%S')] 每日刷新完成" | tee -a "$LOG_FILE"
