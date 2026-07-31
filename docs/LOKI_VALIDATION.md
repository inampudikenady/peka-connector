# Loki Validation

Validation date: 2026-07-30

Endpoint: `http://util001.demo.internal:3100`

Image: `grafana/loki:2.9.8`

## Runtime recovery

The requested endpoint initially refused connections because no Loki container
was running. The preserved `monitoring_loki-data` Docker volume contained Loki
TSDB v13 index, chunk, cache, compactor, and WAL data. Loki was restored with
that volume and the requested host port:

```sh
docker run -d \
  --name loki \
  --restart unless-stopped \
  -p 3100:3100 \
  -v monitoring_loki-data:/data \
  -v /private/tmp/peka-loki-live.yaml:/etc/loki/config.yaml:ro \
  grafana/loki:2.9.8 \
  -config.file=/etc/loki/config.yaml
```

Readiness and version checks:

```sh
curl -fsS http://util001.demo.internal:3100/ready
curl -fsS http://util001.demo.internal:3100/loki/api/v1/status/buildinfo
```

The build-info response reported version `2.9.8`.

## Live schema checks

```sh
curl -fsS http://util001.demo.internal:3100/loki/api/v1/labels
curl -fsS http://util001.demo.internal:3100/loki/api/v1/label/host/values
curl -fsS \
  --get http://util001.demo.internal:3100/loki/api/v1/series \
  --data-urlencode 'match[]={job=~".+"}' \
  --data-urlencode 'start=1783123200000000000' \
  --data-urlencode 'end=1783209600000000000'
```

Results:

- current labels: `channel`, `computer`, `environment`, `host`, `job`, `os`;
- current hosts: `lin001.demo.internal`, `util001.demo.internal`,
  `win001.demo.internal`;
- five current unique streams, including a directly correlatable
  `util001.demo.internal` systemd-journal stream;
- no container or service labels in this dataset.

A wide multi-week series request returned `too many outstanding requests`.
One-day series windows succeeded. The connector therefore uses one-day windows
and unions results across every discovered label.

## Live LogQL check

The following read-only query returned 20 real entries from the preserved
Linux syslog/auth data:

```sh
curl -fsS \
  --get http://util001.demo.internal:3100/loki/api/v1/query_range \
  --data-urlencode 'query={host="peka-linux-001"}' \
  --data-urlencode 'start=1783123200000000000' \
  --data-urlencode 'end=1783209600000000000' \
  --data-urlencode 'limit=20' \
  --data-urlencode 'direction=backward'
```

Observed evidence included Promtail batch-send warnings/errors, systemd service
start events, chronyd clock-interference/time-jump messages, and authentication
session activity.

The product connection test then reported:

- Loki version `2.9.8`;
- six current labels;
- five current streams;
- fixed sample LogQL validated successfully;
- 1.86 seconds for the final 30-day bounded discovery and query validation.

The live `util001` health tool correlated the inventory FQDN to the Loki `host`
label and returned one matched stream. In the 24-hour window it found two
image-signature validation errors; Prometheus simultaneously returned current
CPU, memory, load, disk, filesystem, and process evidence. The connector sorted
these source-attributed observations into one timeline and produced a
deterministic warning assessment with an evidence-specific recommendation.

## Product validation

Automated checks cover:

- dynamic labels rather than a hard-coded host label;
- stream union across discovered labels;
- canonical asset-to-stream correlation and attribution;
- fixed category LogQL construction;
- structured evidence parsing and timestamps;
- explicit `LOKI_STREAM_NOT_FOUND`;
- rejection of caller-supplied `logql`;
- deterministic routing and formatting for log questions;
- evidence sections, timeline, assessment, and recommendations in health
  reports.

Run them with:

```sh
cd /Users/inampudikenady/Documents/peka/peka-connector
.venv/bin/python -m pytest -q backend/tests
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run build

cd /Users/inampudikenady/Documents/peka/peka-saas/backend
env -u DEBUG .venv/bin/python -m pytest -q
```

The Connector UI connection test performs build-info validation, live label
and stream discovery, and a fixed sample LogQL query against a discovered
stream. A successful result therefore validates data access and query execution,
not only TCP reachability.
