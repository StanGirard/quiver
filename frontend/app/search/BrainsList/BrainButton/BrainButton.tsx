"use client";

import { UUID } from "crypto";
import Image from "next/image";

import { useBrainContext } from "@/lib/context/BrainProvider/hooks/useBrainContext";
import { BrainType } from "@/lib/types/BrainConfig";

import styles from "./BrainButton.module.scss";

export interface BrainOrModel {
  name: string;
  description: string;
  id: UUID;
  brain_type: BrainType;
  image_url?: string;
  price?: number;
  display_name?: string;
  snippet_emoji?: string;
  snippet_color?: string;
}
interface BrainButtonProps {
  brainOrModel: BrainOrModel;
  newBrain: () => void;
}

const BrainButton = ({
  brainOrModel,
  newBrain,
}: BrainButtonProps): JSX.Element => {
  const { setCurrentBrainId } = useBrainContext();

  return (
    <div
      className={styles.brain_button_container}
      onClick={() => {
        setCurrentBrainId(brainOrModel.id);
        newBrain();
      }}
    >
      <div className={styles.header}>
        {brainOrModel.image_url ? (
          <Image
            className={styles.brain_image}
            src={brainOrModel.image_url}
            alt="Brain or Model"
            width={24}
            height={24}
          />
        ) : (
          <div className={styles.brain_snippet}>
            <span>{brainOrModel.snippet_emoji}</span>
          </div>
        )}
        <span className={styles.name}>
          {brainOrModel.display_name ?? brainOrModel.name}
        </span>
      </div>
      <span className={styles.description}>{brainOrModel.description}</span>
    </div>
  );
};

export default BrainButton;
