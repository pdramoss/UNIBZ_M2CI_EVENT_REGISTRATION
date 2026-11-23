# The gateway's image. It holds the routing configuration and nothing else: no
# application code, no Python, no database driver. The build context is gateway/
# rather than the repository root, because unlike a backend service it needs
# nothing from common/.
FROM nginx:1.27-alpine

# Rendered by the image's own entrypoint, which runs envsubst over
# /etc/nginx/templates/*.template at container start and writes the result to
# /etc/nginx/conf.d/. Baked in rather than bind-mounted so the image is the whole
# gateway, versioned together with its configuration: the container can then run
# on any host without the repository being present on disk.
#
# NGINX_ENVSUBST_FILTER must still be set at run time, exactly as in Compose, so
# that envsubst replaces only GATEWAY_* and leaves nginx's own runtime variables
# ($request_id, $status, ...) alone.
COPY gateway.conf.template /etc/nginx/templates/gateway.conf.template

# The stock image ships a server on :80 serving /usr/share/nginx/html. This
# gateway listens only on 9000, so drop it: nginx should answer on one port.
RUN rm -f /etc/nginx/conf.d/default.conf

EXPOSE 9000
