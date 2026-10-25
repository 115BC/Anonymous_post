"""Gunicorn 配置：gunicorn -c deploy/gunicorn.conf.py app:app

班级规模下 2 个 worker + 线程足够；SQLite 写入会串行化，worker 不宜过多。
访问日志刻意关闭：匿名反馈/树洞的请求不应在 Web 服务器留下时间与来源记录。
"""

bind = "127.0.0.1:8000"
workers = 2
threads = 4
timeout = 30
graceful_timeout = 30
keepalive = 5

# 不记录访问日志；错误仍写入 journal（不含请求正文）。
accesslog = None
errorlog = "-"
loglevel = "warning"

# 只信任本机 Nginx 传来的代理头。
forwarded_allow_ips = "127.0.0.1"
proxy_allow_ips = "127.0.0.1"
