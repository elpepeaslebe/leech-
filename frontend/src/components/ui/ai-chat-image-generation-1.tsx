"use client";

import * as React from "react";
import { motion } from "motion/react";

export interface ImageGenerationProps {
  children: React.ReactNode;
}

export const ImageGeneration = ({ children }: ImageGenerationProps) => {
  const [progress, setProgress] = React.useState(0);
  const [loadingState, setLoadingState] = React.useState<"starting" | "generating" | "completed">("starting");
  const duration = 30000;

  React.useEffect(() => {
    const startingTimeout = window.setTimeout(() => {
      setLoadingState("generating");
      const startTime = Date.now();
      const interval = window.setInterval(() => {
        const elapsedTime = Date.now() - startTime;
        const progressPercentage = Math.min(100, (elapsedTime / duration) * 100);
        setProgress(progressPercentage);
        if (progressPercentage >= 100) {
          window.clearInterval(interval);
          setLoadingState("completed");
        }
      }, 16);
      return () => window.clearInterval(interval);
    }, 3000);

    return () => window.clearTimeout(startingTimeout);
  }, []);

  return (
    <div className="flex flex-col gap-2">
      <motion.span
        className="bg-[linear-gradient(110deg,var(--color-muted),35%,var(--color-ink),50%,var(--color-muted),75%,var(--color-muted))] bg-[length:200%_100%] bg-clip-text text-base font-medium text-transparent"
        initial={{ backgroundPosition: "200% 0" }}
        animate={{ backgroundPosition: loadingState === "completed" ? "0% 0" : "-200% 0" }}
        transition={{
          repeat: loadingState === "completed" ? 0 : Infinity,
          duration: 3,
          ease: "linear"
        }}
      >
        {loadingState === "starting" && "Getting started."}
        {loadingState === "generating" && "Creating image. May take a moment."}
        {loadingState === "completed" && "Image created."}
      </motion.span>
      <div className="relative max-w-md overflow-hidden rounded-xl border border-border bg-card">
        {children}
        <motion.div
          className="pointer-events-none absolute -top-[25%] h-[125%] w-full backdrop-blur-3xl"
          initial={false}
          animate={{
            clipPath: `polygon(0 ${progress}%, 100% ${progress}%, 100% 100%, 0 100%)`,
            opacity: loadingState === "completed" ? 0 : 1
          }}
          style={{
            clipPath: `polygon(0 ${progress}%, 100% ${progress}%, 100% 100%, 0 100%)`,
            maskImage:
              progress === 0
                ? "linear-gradient(to bottom, black -5%, black 100%)"
                : `linear-gradient(to bottom, transparent ${progress - 5}%, transparent ${progress}%, black ${progress + 5}%)`,
            WebkitMaskImage:
              progress === 0
                ? "linear-gradient(to bottom, black -5%, black 100%)"
                : `linear-gradient(to bottom, transparent ${progress - 5}%, transparent ${progress}%, black ${progress + 5}%)`
          }}
        />
      </div>
    </div>
  );
};

ImageGeneration.displayName = "ImageGeneration";
