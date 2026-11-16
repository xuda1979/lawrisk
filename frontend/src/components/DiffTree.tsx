import { useState } from 'react'
import type { DiffNode } from '../types'

const OP_GLYPH: Record<string, string> = { add: '+', delete: '−', modify: '~' }

function TreeItem({ label, children, items, depth }: DiffNode & { depth: number }) {
  const [open, setOpen] = useState(depth < 2)
  const count = items.length + children.map((c) => c.items.length).reduce((a, b) => a + b, 0)
  return (
    <li className="tree-item">
      <div className="tree-node" style={{ paddingLeft: depth * 16 }}>
        <button className="chevron" onClick={() => setOpen((o) => !o)}>
          {open ? '▾' : '▸'}
        </button>
        <span className="tree-label">{label || '(preamble)'}</span>
        {count > 0 && <span className="tree-count">{count}</span>}
      </div>
      {open && (
        <ul>
          {items.map((it, i) => (
            <li key={i} className={`tree-leaf tree-leaf--${it.op}`}>
              <span className="tree-glyph">{OP_GLYPH[it.op]}</span>
              <span className="tree-leaf-text">{it.summary}</span>
            </li>
          ))}
          {children.map((c, i) => (
            <TreeItem key={i} {...c} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  )
}

export function DiffTree({ root }: { root: DiffNode }) {
  return (
    <ul className="tree">
      {root.children.map((c, i) => (
        <TreeItem key={i} {...c} depth={0} />
      ))}
    </ul>
  )
}
