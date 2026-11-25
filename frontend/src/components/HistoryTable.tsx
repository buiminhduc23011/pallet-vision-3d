import { Button, Empty, Select, Tag } from 'antd';
import { ArrowUpRight, History, RefreshCw } from 'lucide-react';
import type { Verification } from '../api/types';

export default function HistoryTable({
  items,
  next,
  busy,
  filter,
  onFilter,
  onRefresh,
  onMore,
  onOpen,
}: {
  items: Verification[];
  next: string | null;
  busy: boolean;
  filter: string;
  onFilter: (value: string) => void;
  onRefresh: () => void;
  onMore: () => void;
  onOpen: (item: Verification) => void;
}) {
  return (
    <section className="history-panel" id="history">
      <div className="panel-heading">
        <div>
          <span className="section-index">03</span>
          <h2>Inspection history</h2>
          <span className="small-tag">LOCAL AUDIT TRAIL</span>
        </div>
        <div>
          <Select
            size="small"
            aria-label="Filter history by verdict"
            value={filter}
            onChange={onFilter}
            options={['ALL', 'PASS', 'FAIL', 'INCOMPLETE'].map((value) => ({
              value,
              label: value === 'ALL' ? 'All results' : value,
            }))}
          />
          <Button
            type="text"
            aria-label="Refresh inspection history"
            loading={busy}
            icon={<RefreshCw size={15} />}
            onClick={onRefresh}
          />
        </div>
      </div>
      {items.length ? (
        <div className="history-scroll">
          <table>
            <thead>
              <tr>
                <th>Inspection</th>
                <th>Timestamp</th>
                <th>Source</th>
                <th>Roll count</th>
                <th>Matched</th>
                <th>Verdict</th>
                <th aria-label="Open result" />
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td>
                    <code>QC-{item.id.slice(0, 8).toUpperCase()}</code>
                  </td>
                  <td>{new Date(item.created_at).toLocaleString()}</td>
                  <td>
                    <span className="source-label">{item.source}</span> / {item.scope}
                  </td>
                  <td>
                    {item.current_count} <span className="muted">/ {item.reference_count} ref</span>
                  </td>
                  <td>{item.matched_count}</td>
                  <td>
                    <Tag color={item.verdict === 'PASS' ? 'green' : item.verdict === 'FAIL' ? 'red' : 'gold'}>
                      {item.verdict}
                    </Tag>
                  </td>
                  <td>
                    <Button
                      type="text"
                      aria-label={`Open inspection ${item.id.slice(0, 8)}`}
                      icon={<ArrowUpRight size={16} />}
                      onClick={() => onOpen(item)}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty
          image={<History size={27} strokeWidth={1.4} />}
          description={
            <>
              <strong>No verifications yet</strong>
              <span className="empty-history-copy">
                Completed transfer checks are saved here with their original images and settings.
              </span>
            </>
          }
        />
      )}
      <div className="history-footer">
        <span>SQLite storage · snapshots retained on this workstation</span>
        {next && (
          <Button size="small" disabled={busy} onClick={onMore}>
            Load older results
          </Button>
        )}
      </div>
    </section>
  );
}
