import type { SlackBrief } from "../types";

function renderMrkdwn(text: string): string {
  // Minimal Slack mrkdwn -> HTML: bold, italic, inline code, newlines.
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*([^*]+)\*/g, "<strong>$1</strong>")
    // italics only when the underscores wrap whole words — never inside
    // identifiers like CACHE_TTL_SECONDS
    .replace(/(^|[\s>])_([^_\n]+)_(?=[\s.,;:!?)]|$)/gm, "$1<em>$2</em>")
    .replace(/\n/g, "<br/>");
}

export function SlackBriefCard({ brief }: { brief: SlackBrief }) {
  return (
    <div className="slack-card">
      <div className="slack-card-header">
        <span className="slack-icon">#</span>
        <span className="slack-channel">{brief.channel}</span>
      </div>
      <div className="slack-card-body">
        {brief.blocks.map((block, i) => {
          if (block.type === "header") {
            return (
              <div key={i} className="slack-block-header">
                {block.text?.text}
              </div>
            );
          }
          if (block.type === "section" && block.fields) {
            return (
              <div key={i} className="slack-block-fields">
                {block.fields.map((f, j) => (
                  <div
                    key={j}
                    className="slack-field"
                    dangerouslySetInnerHTML={{ __html: renderMrkdwn(f.text) }}
                  />
                ))}
              </div>
            );
          }
          if (block.type === "section" && block.text) {
            return (
              <div
                key={i}
                className="slack-block-section"
                dangerouslySetInnerHTML={{
                  __html: renderMrkdwn(block.text.text),
                }}
              />
            );
          }
          return null;
        })}
      </div>
    </div>
  );
}
