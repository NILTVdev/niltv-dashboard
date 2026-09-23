import type { Post } from "@/lib/types";
import { fmtDate, fmt } from "@/lib/utils";
import { Heart, MessageCircle } from "lucide-react";

interface Props {
  posts: Post[];
}

export default function PostsGrid({ posts }: Props) {
  if (!posts.length) {
    return (
      <p className="text-sm text-[#94a3b8] py-4">No posts available yet.</p>
    );
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
      {posts.map((p) => (
        <a
          key={p.ig_post_id}
          href={p.permalink ?? "#"}
          target="_blank"
          rel="noopener noreferrer"
          className="group relative rounded-xl overflow-hidden border border-[#e2e8f0] bg-[#f8fafc] aspect-square"
        >
          {p.media_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={p.media_url}
              alt={p.caption?.slice(0, 40) ?? "Post"}
              className="w-full h-full object-cover transition-transform group-hover:scale-105"
              loading="lazy"
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-xs text-[#94a3b8]">
              {p.media_type ?? "Post"}
            </div>
          )}
          <div className="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-colors flex flex-col justify-end p-2 opacity-0 group-hover:opacity-100">
            <p className="text-white text-xs font-medium">{fmtDate(p.posted_at)}</p>
            <div className="flex gap-2 text-white text-xs mt-1">
              <span className="flex items-center gap-0.5">
                <Heart size={10} /> {fmt(p.like_count)}
              </span>
              <span className="flex items-center gap-0.5">
                <MessageCircle size={10} /> {fmt(p.comment_count)}
              </span>
            </div>
          </div>
        </a>
      ))}
    </div>
  );
}
