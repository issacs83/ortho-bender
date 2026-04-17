/**
 * DocumentationPage.tsx — Browse and read project documentation.
 *
 * Features:
 *   - Responsive: mobile = single panel (tree or content), desktop = side-by-side
 *   - File tree navigation (from /api/docs/tree)
 *   - Markdown content rendering (from /api/docs/file/{path})
 *   - Download button per file
 *   - Quick links to API docs (/docs, /redoc) — works on any IP (AP/STA/wired)
 */

import { useEffect, useState, useCallback } from 'react';
import {
  FileText, Folder, FolderOpen, Download, ExternalLink,
  ChevronRight, ChevronDown, ChevronLeft, BookOpen, RefreshCw,
} from 'lucide-react';
import { cn } from '../lib/cn';

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
      `<pre style="background:#0f172a;padding:12px;border-radius:6px;overflow-x:auto;font-size:12px;line-height:1.5;border:1px solid rgba(255,255,255,0.10);white-space:pre-wrap;word-break:break-word"><code class="lang-${lang}">${escapeHtml(code.trimEnd())}</code></pre>`)
    // Inline code
    .replace(/`([^`]+)`/g, '<code style="background:rgba(255,255,255,0.10);padding:2px 5px;border-radius:3px;font-size:12px;word-break:break-all">$1</code>')
    // Headers
    .replace(/^#### (.+)$/gm, '<h4 style="margin:16px 0 6px;color:#ECEFF4;font-size:14px">$1</h4>')
    .replace(/^### (.+)$/gm, '<h3 style="margin:20px 0 8px;color:#ECEFF4;font-size:15px">$1</h3>')
    .replace(/^## (.+)$/gm, '<h2 style="margin:24px 0 10px;color:#ECEFF4;font-size:17px;border-bottom:1px solid rgba(255,255,255,0.10);padding-bottom:6px">$1</h2>')
    .replace(/^# (.+)$/gm, '<h1 style="margin:0 0 12px;color:#ECEFF4;font-size:20px;border-bottom:1px solid rgba(255,255,255,0.10);padding-bottom:8px">$1</h1>')
    // Bold / italic
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // Links
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener" style="color:#5B8DEF;text-decoration:underline;word-break:break-all">$1</a>')
    // Tables (simple)
    .replace(/^\|(.+)\|$/gm, (line) => {
      const cells = line.split('|').filter(c => c.trim() !== '');
      if (cells.every(c => /^[\s-:]+$/.test(c))) return '<!-- separator -->';
      const tag = 'td';
      return '<tr>' + cells.map(c =>
        `<${tag} style="padding:4px 8px;border:1px solid rgba(255,255,255,0.10);white-space:nowrap">${c.trim()}</${tag}>`
      ).join('') + '</tr>';
    })
    // Unordered lists
    .replace(/^[-*] (.+)$/gm, '<li style="margin:3px 0">$1</li>')
    // Horizontal rule
    .replace(/^---+$/gm, '<hr style="border:0;border-top:1px solid rgba(255,255,255,0.10);margin:12px 0"/>')
    // Paragraphs (blank lines)
    .replace(/\n\n/g, '</p><p style="margin:6px 0;line-height:1.6">')
    // Single newlines in paragraphs
    .replace(/\n/g, '<br/>');

  // Wrap table rows — overflow scrollable
  html = html.replace(/((?:<tr>.*?<\/tr>\s*(?:<!-- separator -->\s*)?)+)/g,
    '<div style="overflow-x:auto;margin:10px 0"><table style="border-collapse:collapse;font-size:12px;min-width:100%">$1</table></div>');
  html = html.replace(/<!-- separator -->/g, '');

  // Wrap list items
  html = html.replace(/((?:<li[^>]*>.*?<\/li>\s*)+)/g, '<ul style="padding-left:18px;margin:6px 0">$1</ul>');

  return `<div><p style="margin:6px 0;line-height:1.6">${html}</p></div>`;
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

  const paddingLeft = 8 + depth * 14;

  if (isDir) {
    const dir = node as DocDir;
    return (
      <>
        <button
          style={{ paddingLeft }}
          className={cn(
            'flex items-center gap-1.5 pr-2 py-1.5 cursor-pointer text-[13px] rounded',
            'bg-transparent border-none w-full text-left text-text-secondary hover:text-text-primary',
            'hover:bg-surface-2 transition-colors',
          )}
          onClick={() => setOpen(o => !o)}
        >
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          {open
            ? <FolderOpen size={14} className="text-warning shrink-0" />
            : <Folder size={14} className="text-warning shrink-0" />
          }
          <span className="font-medium overflow-hidden text-ellipsis whitespace-nowrap">{dir.name}</span>
        </button>
        {open && dir.children.map(c => (
          <TreeItem key={c.path} node={c} selected={selected} onSelect={onSelect} depth={depth + 1} />
        ))}
      </>
    );
  }

  return (
    <button
      style={{ paddingLeft }}
      className={cn(
        'flex items-center gap-1.5 pr-2 py-1.5 cursor-pointer text-[13px] rounded',
        'border-none w-full text-left transition-colors',
        isActive
          ? 'bg-info/12 text-accent'
          : 'bg-transparent text-text-secondary hover:text-text-primary hover:bg-surface-2',
      )}
      onClick={() => onSelect(node.path)}
    >
      <FileText size={14} className="shrink-0" />
      <span className="overflow-hidden text-ellipsis whitespace-nowrap">{node.name.replace(/\.md$/, '')}</span>
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
  const [isMobile, setIsMobile] = useState(window.innerWidth < 768);

  useEffect(() => {
    function onResize() { setIsMobile(window.innerWidth < 768); }
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

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

  function handleSelect(path: string) {
    setSelectedPath(path);
  }

  function handleBack() {
    setSelectedPath(null);
    setContent('');
  }

  // Mobile: show tree OR content, not both
  const showTree = !isMobile || !selectedPath;
  const showContent = !isMobile || !!selectedPath;

  return (
    <div className={cn('max-w-[1400px] mx-auto', isMobile ? 'p-3' : 'p-5')}>
      {/* Page header */}
      <div className="flex items-center gap-2.5 mb-4">
        <BookOpen size={20} className="text-info" />
        <h2 className="m-0 text-[18px] text-text-primary font-semibold">Documentation</h2>
      </div>

      {/* Quick links — use current origin so it works on any IP */}
      <div className="flex gap-2.5 mb-4 flex-wrap">
        <a
          href={`${window.location.origin}/docs`}
          target="_blank"
          rel="noopener"
          className={cn(
            'flex items-center gap-1.5 px-3.5 py-1.5 rounded-md border border-border no-underline',
            'bg-info/12 text-accent text-[13px] font-medium hover:opacity-80 transition-opacity',
          )}
        >
          <ExternalLink size={14} /> Swagger UI
        </a>
        <a
          href={`${window.location.origin}/redoc`}
          target="_blank"
          rel="noopener"
          className={cn(
            'flex items-center gap-1.5 px-3.5 py-1.5 rounded-md border border-border no-underline',
            'bg-info/12 text-accent text-[13px] font-medium hover:opacity-80 transition-opacity',
          )}
        >
          <ExternalLink size={14} /> ReDoc
        </a>
      </div>

      {/* Main layout */}
      <div className="flex gap-4 items-start">

        {/* File tree panel */}
        {showTree && (
          <div
            className={cn(
              'bg-surface-1 border border-border rounded-lg shrink-0',
              'pt-2.5 pb-2.5 px-1.5 overflow-y-auto',
              isMobile ? 'w-full' : 'w-[260px] min-w-[200px]',
            )}
            style={{ maxHeight: isMobile ? undefined : 'calc(100vh - 220px)' }}
          >
            <div className="flex items-center justify-between px-2 pb-2 border-b border-border mb-1.5">
              <span className="text-[11px] font-semibold text-text-tertiary uppercase tracking-wider">
                Files
              </span>
              <button
                onClick={loadTree}
                className="bg-transparent border-none cursor-pointer text-text-tertiary p-0.5 hover:text-text-secondary transition-colors"
                title="Refresh"
              >
                <RefreshCw size={13} />
              </button>
            </div>
            {tree.length === 0 ? (
              <div className="p-4 text-center text-text-tertiary text-[13px]">
                No documentation files found.
              </div>
            ) : (
              tree.map(node => (
                <TreeItem key={node.path} node={node} selected={selectedPath} onSelect={handleSelect} />
              ))
            )}
          </div>
        )}

        {/* Content panel */}
        {showContent && (
          <div
            className={cn(
              'bg-surface-1 border border-border rounded-lg flex-1 min-w-0 overflow-x-hidden',
              isMobile ? 'w-full p-3.5' : 'p-6',
              isMobile ? 'min-h-[300px]' : 'min-h-[400px]',
            )}
          >
            {!selectedPath && !isMobile && (
              <div className="text-center pt-20 text-text-tertiary">
                <BookOpen size={48} className="opacity-30 mx-auto mb-4" />
                <p className="text-[15px]">Select a document to view it here.</p>
                <p className="text-[13px] mt-2">
                  Or visit the{' '}
                  <a href={`${window.location.origin}/docs`} target="_blank" rel="noopener" className="text-accent underline">
                    API Reference
                  </a>{' '}
                  for endpoint documentation.
                </p>
              </div>
            )}
            {loading && (
              <div className="text-center pt-16 text-text-tertiary">Loading...</div>
            )}
            {error && (
              <div className="text-danger p-4">{error}</div>
            )}
            {selectedPath && !loading && !error && (
              <>
                {/* File header with back button on mobile */}
                <div className="flex items-center justify-between mb-3 pb-2.5 border-b border-border gap-2">
                  <div className="flex items-center gap-1.5 min-w-0 flex-1">
                    {isMobile && (
                      <button
                        onClick={handleBack}
                        className="bg-transparent border-none cursor-pointer text-accent p-0.5 shrink-0 hover:opacity-80"
                      >
                        <ChevronLeft size={18} />
                      </button>
                    )}
                    <span className="text-[12px] text-text-tertiary font-mono overflow-hidden text-ellipsis whitespace-nowrap">
                      {selectedPath}
                    </span>
                  </div>
                  <a
                    href={`${BASE}/api/docs/download/${selectedPath}`}
                    download
                    className={cn(
                      'flex items-center gap-1 text-[12px] shrink-0 no-underline',
                      'text-accent px-2.5 py-1 rounded border border-border/60 bg-info/12',
                      'hover:opacity-80 transition-opacity',
                    )}
                  >
                    <Download size={13} /> Download
                  </a>
                </div>
                {/* Rendered markdown */}
                <div
                  className="text-text-secondary text-[13px] leading-relaxed break-words overflow-x-auto"
                  style={{ overflowWrap: 'break-word' }}
                  dangerouslySetInnerHTML={{ __html: markdownToHtml(content) }}
                />
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
