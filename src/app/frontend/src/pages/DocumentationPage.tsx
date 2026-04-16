/**
 * DocumentationPage.tsx — Browse and read project documentation.
 *
 * Features:
 *   - File tree navigation (from /api/docs/tree)
 *   - Markdown content rendering (from /api/docs/file/{path})
 *   - Download button per file
 *   - Quick links to API docs (/docs, /redoc)
 */

import { useEffect, useState, useCallback, type CSSProperties } from 'react';
import { FileText, Folder, FolderOpen, Download, ExternalLink, ChevronRight, ChevronDown, BookOpen, RefreshCw } from 'lucide-react';
import { BG_PANEL, BORDER, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED, COLOR_INFO, COLOR_INFO_BG } from '../constants';

const BASE = import.meta.env.VITE_API_BASE ?? '';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DocFile {
  type: 'file';
  name: string;
  path: string;
  size: number;
}

interface DocDir {
  type: 'dir';
  name: string;
  path: string;
  children: DocNode[];
}

type DocNode = DocFile | DocDir;

// ---------------------------------------------------------------------------
// Simple markdown to HTML
// ---------------------------------------------------------------------------

function markdownToHtml(md: string): string {
  let html = md
    // Code blocks (fenced)
    .replace(/```(\w*)\n([\s\S]*?)```/g, (_m, lang, code) =>
      `<pre style="background:#0f172a;padding:12px;border-radius:6px;overflow-x:auto;font-size:13px;line-height:1.5;border:1px solid #334155"><code class="lang-${lang}">${escapeHtml(code.trimEnd())}</code></pre>`)
    // Inline code
    .replace(/`([^`]+)`/g, '<code style="background:#334155;padding:2px 6px;border-radius:3px;font-size:13px">$1</code>')
    // Headers
    .replace(/^#### (.+)$/gm, '<h4 style="margin:20px 0 8px;color:#f1f5f9;font-size:14px">$1</h4>')
    .replace(/^### (.+)$/gm, '<h3 style="margin:24px 0 10px;color:#f1f5f9;font-size:16px">$1</h3>')
    .replace(/^## (.+)$/gm, '<h2 style="margin:28px 0 12px;color:#f1f5f9;font-size:18px;border-bottom:1px solid #334155;padding-bottom:6px">$1</h2>')
    .replace(/^# (.+)$/gm, '<h1 style="margin:0 0 16px;color:#f1f5f9;font-size:22px;border-bottom:1px solid #334155;padding-bottom:8px">$1</h1>')
    // Bold / italic
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // Links
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener" style="color:#60a5fa;text-decoration:underline">$1</a>')
    // Tables (simple)
    .replace(/^\|(.+)\|$/gm, (line) => {
      const cells = line.split('|').filter(c => c.trim() !== '');
      if (cells.every(c => /^[\s-:]+$/.test(c))) return '<!-- separator -->';
      const tag = 'td';
      return '<tr>' + cells.map(c => `<${tag} style="padding:6px 12px;border:1px solid #334155">${c.trim()}</${tag}>`).join('') + '</tr>';
    })
    // Unordered lists
    .replace(/^[-*] (.+)$/gm, '<li style="margin:4px 0">$1</li>')
    // Horizontal rule
    .replace(/^---+$/gm, '<hr style="border:0;border-top:1px solid #334155;margin:16px 0"/>')
    // Paragraphs (blank lines)
    .replace(/\n\n/g, '</p><p style="margin:8px 0;line-height:1.7">')
    // Single newlines in paragraphs
    .replace(/\n/g, '<br/>');

  // Wrap table rows
  html = html.replace(/((?:<tr>.*?<\/tr>\s*(?:<!-- separator -->\s*)?)+)/g,
    '<table style="border-collapse:collapse;width:100%;margin:12px 0;font-size:13px">$1</table>');
  html = html.replace(/<!-- separator -->/g, '');

  // Wrap list items
  html = html.replace(/((?:<li[^>]*>.*?<\/li>\s*)+)/g, '<ul style="padding-left:20px;margin:8px 0">$1</ul>');

  return `<div><p style="margin:8px 0;line-height:1.7">${html}</p></div>`;
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ---------------------------------------------------------------------------
// Tree item component
// ---------------------------------------------------------------------------

function TreeItem({ node, selected, onSelect, depth = 0 }: {
  node: DocNode; selected: string | null; onSelect: (path: string) => void; depth?: number;
}) {
  const [open, setOpen] = useState(depth < 1);
  const isDir = node.type === 'dir';
  const isActive = !isDir && node.path === selected;

  const style: CSSProperties = {
    display: 'flex', alignItems: 'center', gap: 6,
    padding: `6px 8px 6px ${8 + depth * 16}px`,
    cursor: 'pointer', fontSize: 13, borderRadius: 4,
    background: isActive ? COLOR_INFO_BG : 'transparent',
    color: isActive ? '#93c5fd' : TEXT_SECONDARY,
    border: 'none', width: '100%', textAlign: 'left',
  };

  if (isDir) {
    const dir = node as DocDir;
    return (
      <>
        <button style={style} onClick={() => setOpen(o => !o)}>
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          {open ? <FolderOpen size={14} color="#f59e0b" /> : <Folder size={14} color="#f59e0b" />}
          <span style={{ fontWeight: 500 }}>{dir.name}</span>
        </button>
        {open && dir.children.map(c => (
          <TreeItem key={c.path} node={c} selected={selected} onSelect={onSelect} depth={depth + 1} />
        ))}
      </>
    );
  }

  return (
    <button style={style} onClick={() => onSelect(node.path)}>
      <FileText size={14} />
      <span>{node.name.replace(/\.md$/, '')}</span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function DocumentationPage() {
  const [tree, setTree] = useState<DocNode[]>([]);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [content, setContent] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load file tree
  const loadTree = useCallback(() => {
    fetch(`${BASE}/api/docs/tree`).then(r => r.json()).then(j => {
      if (j.success) setTree(j.data);
    }).catch(() => null);
  }, []);

  useEffect(() => { loadTree(); }, [loadTree]);

  // Load file content
  useEffect(() => {
    if (!selectedPath) return;
    setLoading(true);
    setError(null);
    fetch(`${BASE}/api/docs/file/${selectedPath}`)
      .then(r => r.json())
      .then(j => {
        if (j.success) setContent(j.data.content);
        else setError(j.detail ?? 'Failed to load file');
      })
      .catch(() => setError('Network error'))
      .finally(() => setLoading(false));
  }, [selectedPath]);

  const panelStyle: CSSProperties = {
    background: BG_PANEL, borderRadius: 8, border: `1px solid ${BORDER}`,
  };

  return (
    <div style={{ padding: 20, maxWidth: 1400, margin: '0 auto' }}>
      {/* Page header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20 }}>
        <BookOpen size={22} color={COLOR_INFO} />
        <h2 style={{ margin: 0, fontSize: 20, color: TEXT_PRIMARY }}>Documentation</h2>
      </div>

      {/* Quick links */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
        <a href="/docs" target="_blank" rel="noopener"
          style={{ ...linkCardStyle, textDecoration: 'none' }}>
          <ExternalLink size={14} /> API Reference (Swagger)
        </a>
        <a href="/redoc" target="_blank" rel="noopener"
          style={{ ...linkCardStyle, textDecoration: 'none' }}>
          <ExternalLink size={14} /> API Reference (ReDoc)
        </a>
      </div>

      {/* Main layout: tree + content */}
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
        {/* File tree panel */}
        <div style={{ ...panelStyle, width: 260, minWidth: 220, flexShrink: 0, padding: '12px 8px', maxHeight: 'calc(100vh - 200px)', overflowY: 'auto' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 8px 8px', borderBottom: `1px solid ${BORDER}`, marginBottom: 8 }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: TEXT_MUTED, textTransform: 'uppercase', letterSpacing: 1 }}>Files</span>
            <button onClick={loadTree} style={{ background: 'none', border: 'none', cursor: 'pointer', color: TEXT_MUTED, padding: 2 }} title="Refresh">
              <RefreshCw size={13} />
            </button>
          </div>
          {tree.length === 0 ? (
            <div style={{ padding: 16, textAlign: 'center', color: TEXT_MUTED, fontSize: 13 }}>
              No documentation files found.
            </div>
          ) : (
            tree.map(node => (
              <TreeItem key={node.path} node={node} selected={selectedPath} onSelect={setSelectedPath} />
            ))
          )}
        </div>

        {/* Content panel */}
        <div style={{ ...panelStyle, flex: 1, minWidth: 0, padding: 24, minHeight: 400 }}>
          {!selectedPath && (
            <div style={{ textAlign: 'center', paddingTop: 80, color: TEXT_MUTED }}>
              <BookOpen size={48} style={{ opacity: 0.3, marginBottom: 16 }} />
              <p style={{ fontSize: 15 }}>Select a document from the sidebar to view it here.</p>
              <p style={{ fontSize: 13, marginTop: 8 }}>
                Or visit the <a href="/docs" target="_blank" rel="noopener" style={{ color: '#60a5fa' }}>API Reference</a> for endpoint documentation.
              </p>
            </div>
          )}
          {loading && (
            <div style={{ textAlign: 'center', paddingTop: 80, color: TEXT_MUTED }}>Loading...</div>
          )}
          {error && (
            <div style={{ color: '#ef4444', padding: 16 }}>{error}</div>
          )}
          {selectedPath && !loading && !error && (
            <>
              {/* File header */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, paddingBottom: 12, borderBottom: `1px solid ${BORDER}` }}>
                <span style={{ fontSize: 13, color: TEXT_MUTED, fontFamily: 'monospace' }}>{selectedPath}</span>
                <a
                  href={`${BASE}/api/docs/download/${selectedPath}`}
                  download
                  style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: '#60a5fa', textDecoration: 'none', padding: '4px 10px', borderRadius: 4, border: '1px solid #334155', background: '#1e3a5f' }}
                >
                  <Download size={13} /> Download
                </a>
              </div>
              {/* Rendered markdown */}
              <div
                style={{ color: TEXT_SECONDARY, fontSize: 14, lineHeight: 1.7, wordBreak: 'break-word' }}
                dangerouslySetInnerHTML={{ __html: markdownToHtml(content) }}
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}

const linkCardStyle: CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 6,
  padding: '8px 16px', borderRadius: 6,
  background: COLOR_INFO_BG, color: '#93c5fd',
  fontSize: 13, fontWeight: 500,
  border: `1px solid ${BORDER}`,
};
