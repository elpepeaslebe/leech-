"use client";

import { motion } from "motion/react";

type ShiningTextProps = {
  text: string;
  className?: string;
};

export function ShiningText({ text, className = "" }: ShiningTextProps) {
  return (
    <motion.span
      className={[
        "inline-block bg-[linear-gradient(110deg,var(--color-muted),35%,var(--color-ink),50%,var(--color-muted),75%,var(--color-muted))] bg-[length:200%_100%] bg-clip-text text-transparent",
        className
      ].join(" ")}
      initial={{ backgroundPosition: "200% 0" }}
      animate={{ backgroundPosition: "-200% 0" }}
      transition={{
        repeat: Infinity,
        duration: 2,
        ease: "linear"
      }}
    >
      {text}
    </motion.span>
  );
}
