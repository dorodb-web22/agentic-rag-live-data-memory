import React from 'react';
import { ExternalLink, Layers, CheckSquare } from 'lucide-react';

export function CitationBadge({ tag, sources, onSelectSource }) {
  // Parse tag e.g. "Jira #JIRA-101" or "Notion #NOTION-3"
  const isJira = tag.toLowerCase().includes('jira');
  const isNotion = tag.toLowerCase().includes('notion');

  // Extract ID e.g. "JIRA-101" or "NOTION-3"
  const cleanIdMatch = tag.match(/(JIRA-\d+|NOTION-\d+|[A-Za-z0-9-]+)/i);
  const matchedId = cleanIdMatch ? cleanIdMatch[0].toUpperCase() : tag;

  // Find source item if available
  const matchingSource = (sources || []).find(s => 
    s.source_id && s.source_id.toUpperCase() === matchedId
  );

  const handleClick = (e) => {
    e.stopPropagation();
    if (matchingSource && onSelectSource) {
      onSelectSource(matchingSource);
    } else if (onSelectSource) {
      // Fallback dummy structure if matching source not explicitly passed
      onSelectSource({
        source: isJira ? 'jira' : 'notion',
        source_id: matchedId,
        title: matchingSource?.title || `${isJira ? 'Jira Ticket' : 'Notion Document'} ${matchedId}`,
        snippet: matchingSource?.snippet || 'Source evidence snippet retrieved during query decomposition.',
        url: matchingSource?.url || '#'
      });
    }
  };

  return (
    <button
      onClick={handleClick}
      className={`inline-flex items-center gap-1 px-2 py-0.5 mx-0.5 rounded-md text-xs font-mono font-medium transition-all duration-200 border cursor-pointer select-none shadow-sm hover:scale-105 ${
        isJira
          ? 'bg-blue-950/60 text-blue-300 border-blue-500/40 hover:bg-blue-900/80 hover:border-blue-400 hover:text-blue-200 shadow-blue-950/50'
          : isNotion
          ? 'bg-purple-950/60 text-purple-300 border-purple-500/40 hover:bg-purple-900/80 hover:border-purple-400 hover:text-purple-200 shadow-purple-950/50'
          : 'bg-slate-800 text-slate-300 border-slate-600 hover:bg-slate-700'
      }`}
      title={matchingSource ? `Click to view source: ${matchingSource.title}` : `Click to inspect ${tag}`}
    >
      {isJira ? (
        <CheckSquare className="w-3 h-3 text-blue-400 shrink-0" />
      ) : isNotion ? (
        <Layers className="w-3 h-3 text-purple-400 shrink-0" />
      ) : (
        <ExternalLink className="w-3 h-3 shrink-0" />
      )}
      <span>{tag}</span>
    </button>
  );
}

/**
 * Custom renderer for markdown text that converts inline citation tags [Jira #JIRA-101] or [Notion #NOTION-3] 
 * into interactive CitationBadge components.
 */
export function CitedText({ text, sources, onSelectSource }) {
  if (!text) return null;

  // Regex matches tags like [Jira #JIRA-101], [Notion #NOTION-3], [Jira JIRA-101], [Notion NOTION-3]
  const citationRegex = /\[(Jira|Notion)\s*#?([A-Za-z0-9-]+)\]/gi;
  
  const parts = [];
  let lastIndex = 0;
  let match;

  while ((match = citationRegex.exec(text)) !== null) {
    // Push preceding text segment
    if (match.index > lastIndex) {
      parts.push({
        type: 'text',
        content: text.slice(lastIndex, match.index)
      });
    }

    const sourceType = match[1];
    const sourceId = match[2];
    const fullTag = `${sourceType} #${sourceId}`;

    parts.push({
      type: 'citation',
      tag: fullTag,
      sourceType: sourceType.toLowerCase(),
      sourceId: sourceId
    });

    lastIndex = citationRegex.lastIndex;
  }

  // Push remaining text
  if (lastIndex < text.length) {
    parts.push({
      type: 'text',
      content: text.slice(lastIndex)
    });
  }

  return (
    <div className="prose prose-invert max-w-none text-slate-200 text-sm md:text-base leading-relaxed whitespace-pre-wrap">
      {parts.map((part, idx) => {
        if (part.type === 'text') {
          return <span key={idx}>{part.content}</span>;
        }
        return (
          <CitationBadge
            key={idx}
            tag={part.tag}
            sources={sources}
            onSelectSource={onSelectSource}
          />
        );
      })}
    </div>
  );
}
