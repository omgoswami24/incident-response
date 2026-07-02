import ReactMarkdown from "react-markdown";

export function PostmortemView({ markdown }: { markdown: string }) {
  return (
    <div className="postmortem">
      <ReactMarkdown>{markdown}</ReactMarkdown>
    </div>
  );
}
