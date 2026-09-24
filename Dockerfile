FROM python:3.11-slim

# 零第三方依赖：纯标准库实现，镜像内不做 pip 安装。
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AUDIT_HOST=0.0.0.0 \
    AUDIT_PORT=8080

WORKDIR /srv

COPY app ./app
COPY tests ./tests
COPY verify ./verify

# 构建检查：全部源码可编译（verify 服务也会独立再跑一次）。
RUN python -m compileall -q app verify

EXPOSE 8080

# 健康检查：只有请求校验器与扫描引擎均完成自检并就绪才返回 200。
HEALTHCHECK --interval=3s --timeout=3s --start-period=2s --retries=10 \
    CMD python -c "import urllib.request,sys; r=urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3); sys.exit(0 if r.status==200 else 1)"

CMD ["python", "-m", "app.server"]
