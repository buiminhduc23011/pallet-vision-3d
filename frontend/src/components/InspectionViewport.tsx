import { useRef, useState } from 'react';
import { Crosshair, ImagePlus, Layers3, Maximize2, ScanLine } from 'lucide-react';
import { Button, Checkbox, Segmented, Tooltip } from 'antd';
import type { Config, Inspection, Point, ROI, Session, Verification } from '../api/types';

type Props = {
  session: Session | null;
  inspection: Inspection | null;
  verification: Verification | null;
  config: Config | null;
  busy: boolean;
  onUpload: () => void;
  onROI: (roi: ROI) => void;
  onFloorROI: (roi: ROI) => void;
  onOrigin: (point: Point) => void;
};
const points = (p: Point[]) => p.map((v) => v.join(',')).join(' ');

export default function InspectionViewport({
  session,
  inspection,
  verification,
  config,
  busy,
  onUpload,
  onROI,
  onFloorROI,
  onOrigin,
}: Props) {
  const [view, setView] = useState('RGB');
  const [layers, setLayers] = useState(['ROI zone', 'Pallet', 'Rolls', 'Transfer diff']);
  const [drawing, setDrawing] = useState<'roi' | 'floor' | 'origin' | null>(null);
  const [draft, setDraft] = useState<Point[] | null>(null);
  const start = useRef<Point | null>(null);
  const container = useRef<HTMLDivElement>(null);
  const [showLive, setShowLive] = useState(true);
  const live = session?.mode === 'live' && showLive;
  const bagPlaying = session?.frame?.source === 'bag' && session.playback === 'playing';
  const streaming = live || bagPlaying;
  const frame = streaming ? session?.frame : (inspection?.frame ?? session?.frame);
  const width = frame?.width ?? 1280,
    height = frame?.height ?? 720;
  const hasDepth = !!frame?.capabilities.depth;
  const effectiveView = hasDepth ? view : 'RGB';
  const source =
    streaming && session?.frame
      ? `/api/v1/sessions/${session.id}/stream.mjpg?view=${effectiveView === 'Depth' ? 'depth' : 'rgb'}`
      : inspection?.image_urls[effectiveView === 'Depth' ? 'depth' : 'rgb'];
  const overlayInspection = !streaming ? inspection : null;
  function coordinate(event: React.PointerEvent<SVGSVGElement>): Point {
    const rect = event.currentTarget.getBoundingClientRect();
    return [
      Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
      Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
    ];
  }
  function finish() {
    if (draft && start.current) {
      const area = Math.abs((draft[2][0] - draft[0][0]) * (draft[2][1] - draft[0][1]));
      if (area > 0.0001) (drawing === 'floor' ? onFloorROI : onROI)({ points: draft });
    }
    start.current = null;
    setDraft(null);
    setDrawing(null);
  }
  const scalePoints = (p: Point[]) => p.map(([x, y]) => [x * (width - 1), y * (height - 1)] as Point);
  const taught =
    config?.teaching?.image_width === width && config?.teaching?.image_height === height
      ? config.teaching
      : null;
  return (
    <section className="viewport-panel" ref={container} aria-label="Inspection viewport">
      <div className="panel-heading">
        <div>
          <span className="section-index">01</span>
          <h2>Inspection viewport</h2>
          <span className="small-tag">{inspection?.scope ?? 'NO INPUT'}</span>
        </div>
        <Tooltip title="Fullscreen viewport">
          <Button
            type="text"
            aria-label="Fullscreen viewport"
            icon={<Maximize2 size={16} />}
            onClick={() => container.current?.requestFullscreen()}
          />
        </Tooltip>
      </div>
      <div className="viewport-toolbar">
        <Segmented
          size="small"
          value={effectiveView}
          onChange={(v) => setView(v)}
          options={[
            { label: 'RGB', value: 'RGB' },
            { label: 'Depth', value: 'Depth', disabled: !hasDepth },
          ]}
        />
        <div className="toolbar-actions">
          {session?.mode === 'live' && (
            <Checkbox checked={!showLive} onChange={(e) => setShowLive(!e.target.checked)}>
              Pinned inspection
            </Checkbox>
          )}
          <Button
            size="small"
            type={drawing === 'roi' ? 'primary' : 'text'}
            disabled={!source || busy}
            icon={<Crosshair size={14} />}
            onClick={() => setDrawing(drawing === 'roi' ? null : 'roi')}
          >
            Search ROI
          </Button>
          {taught && (
            <Button
              size="small"
              type={drawing === 'origin' ? 'primary' : 'default'}
              disabled={busy || streaming || !inspection?.pallet}
              onClick={() => setDrawing(drawing === 'origin' ? null : 'origin')}
            >
              Confirm origin
            </Button>
          )}
          <Button
            size="small"
            type={drawing === 'floor' ? 'primary' : 'text'}
            disabled={!source || !hasDepth || busy || streaming}
            onClick={() => setDrawing(drawing === 'floor' ? null : 'floor')}
          >
            Floor sample
          </Button>
        </div>
      </div>
      {drawing === 'origin' && (
        <div className="origin-prompt">
          Select the same physical origin corner taught as O, not the corner nearest the screen origin.{' '}
          {inspection?.pallet?.polygon.map((p, i) => (
            <Button
              key={i}
              size="small"
              disabled={busy || streaming}
              onClick={() => {
                onOrigin([p[0] / (width - 1), p[1] / (height - 1)]);
                setDrawing(null);
              }}
            >
              Corner {i + 1}
            </Button>
          ))}
        </div>
      )}
      <div className={`viewport ${drawing ? 'is-drawing' : ''}`}>
        <div className="viewport-topline">
          <span>
            <i className={`status-dot ${source ? 'on' : ''}`} />
            {live ? 'LIVE FEED' : source ? 'PINNED FRAME' : 'AWAITING INPUT'}
          </span>
          <span>{source ? `${width} × ${height}` : 'REAL INPUTS ONLY'}</span>
        </div>
        {source ? (
          <div className="image-stage" style={{ aspectRatio: `${width}/${height}` }}>
            <img
              src={source}
              alt={view === 'Depth' ? 'Depth colormap of the loaded frame' : 'Actual pallet inspection frame'}
              draggable={false}
            />
            <svg
              viewBox={`0 0 ${width} ${height}`}
              className="overlay"
              aria-label="Inspection overlays and ROI drawing surface"
              onPointerDown={(e) => {
                if (!drawing || busy) return;
                if (drawing === 'origin') {
                  if (!streaming) {
                    onOrigin(coordinate(e));
                    setDrawing(null);
                  }
                  return;
                }
                e.currentTarget.setPointerCapture(e.pointerId);
                start.current = coordinate(e);
              }}
              onPointerMove={(e) => {
                if (!start.current) return;
                const [x, y] = coordinate(e),
                  [sx, sy] = start.current;
                setDraft([
                  [sx, sy],
                  [x, sy],
                  [x, y],
                  [sx, y],
                ]);
              }}
              onPointerUp={finish}
              onPointerCancel={() => {
                start.current = null;
                setDraft(null);
              }}
            >
              {taught && (
                <g stroke="#ffcd4a" fill="none" strokeWidth={2}>
                  {overlayInspection?.alignment.acceptance_polygon && (
                    <polygon
                      points={points(overlayInspection.alignment.acceptance_polygon)}
                      fill="#ffcd4a"
                      fillOpacity={0.12}
                      strokeDasharray="4 3"
                    />
                  )}
                  <polygon points={points(scalePoints(taught.target.points))} strokeDasharray="7 5" />
                  <polyline
                    points={points(
                      scalePoints([
                        taught.target.points[1],
                        taught.target.points[0],
                        taught.target.points[3],
                      ]),
                    )}
                  />
                  {taught.target.points.map(([x, y], i) => (
                    <text
                      key={i}
                      x={x * (width - 1) + 6}
                      y={y * (height - 1) - 6}
                      fill="#ffcd4a"
                      stroke="#17232c"
                      paintOrder="stroke"
                      fontSize={Math.max(width / 65, 12)}
                    >
                      {['O', '+X', '2', '+Y'][i]}
                    </text>
                  ))}
                </g>
              )}
              {drawing === 'origin' &&
                overlayInspection?.pallet?.polygon.map(([x, y], i) => (
                  <g key={i}>
                    <circle cx={x} cy={y} r={8} fill="#ffcd4a" />
                    <text x={x + 10} y={y + 18} fill="white" fontSize={18}>
                      {i + 1}
                    </text>
                  </g>
                ))}
              {layers.includes('ROI zone') && config && (
                <polygon points={points(scalePoints(config.roi.points))} className="roi-polygon" />
              )}
              {draft && (
                <polygon
                  points={points(scalePoints(draft))}
                  className={`draft-polygon ${drawing === 'floor' ? 'floor' : ''}`}
                />
              )}
              {overlayInspection && layers.includes('Pallet') && overlayInspection.pallet && (
                <polygon points={points(overlayInspection.pallet.polygon)} className="pallet-polygon" />
              )}
              {overlayInspection &&
                layers.includes('Rolls') &&
                overlayInspection.rolls.map((roll) => {
                  const pair = verification?.pairs.find((p) => p.current_roll_id === roll.id);
                  const bad = pair?.reasons.length || verification?.extra.some((r) => r.id === roll.id);
                  const color =
                    verification && verification.verdict !== 'INCOMPLETE' && layers.includes('Transfer diff')
                      ? bad
                        ? '#f08433'
                        : '#44c88a'
                      : '#4ac8e8';
                  return (
                    <g key={roll.id}>
                      <image
                        href={roll.mask_url}
                        width={width}
                        height={height}
                        opacity={0.15}
                        style={{ mixBlendMode: 'screen' }}
                      />
                      <polygon
                        points={points(roll.rotated_box)}
                        fill="none"
                        stroke={color}
                        strokeWidth={2}
                        vectorEffect="non-scaling-stroke"
                      />
                      <text
                        x={roll.centroid[0]}
                        y={roll.centroid[1]}
                        fill={color}
                        fontSize={Math.max(width / 70, 12)}
                      >
                        {roll.id} · {pair?.reasons.join(', ') || roll.orientation}
                      </text>
                    </g>
                  );
                })}
              {!streaming &&
                verification &&
                layers.includes('Transfer diff') &&
                verification.missing.map(
                  (roll) =>
                    roll.expected_box && (
                      <g key={roll.id}>
                        <polygon points={points(roll.expected_box)} className="missing-polygon" />
                        <text
                          x={roll.expected_box[0][0]}
                          y={roll.expected_box[0][1]}
                          fill="#ff6d6d"
                          fontSize={Math.max(width / 70, 12)}
                        >
                          MISSING {roll.id}
                        </text>
                      </g>
                    ),
                )}
            </svg>
          </div>
        ) : (
          <div className="empty-viewport">
            <div className="empty-focus">
              <ScanLine size={44} strokeWidth={1} />
              <span />
              <span />
              <span />
              <span />
            </div>
            <h3>A clear view starts here.</h3>
            <p>
              Load a real pallet image or connect your RealSense camera.
              <br />
              Inspection results appear only after processing.
            </p>
            <Button icon={<ImagePlus size={16} />} onClick={onUpload} disabled={busy}>
              Load inspection image
            </Button>
            <div className="supported-formats">
              JPG / PNG <span>·</span> RGB + DEPTH <span>·</span> REALSENSE BAG
            </div>
          </div>
        )}
        {drawing && (
          <div className="drawing-hint">
            {drawing === 'floor'
              ? 'Drag over a visible, bare floor patch'
              : 'Drag to define the target pallet zone'}
          </div>
        )}
        <div className="viewport-bottomline">
          <span>
            {busy
              ? 'PROCESSING…'
              : source
                ? live
                  ? 'Live preview · capture to inspect'
                  : 'Immutable frame · overlays synchronized'
                : 'No image loaded'}
          </span>
          <span>{inspection ? `CFG ${String(inspection.config_revision).padStart(3, '0')}` : '—'}</span>
        </div>
      </div>
      <div className="layers-bar">
        <Layers3 size={15} />
        <span>Overlays</span>
        <Checkbox.Group
          value={layers}
          onChange={(v) => setLayers(v as string[])}
          options={['ROI zone', 'Pallet', 'Rolls', 'Transfer diff']}
        />
      </div>
    </section>
  );
}
