import React, { useState } from "react";

import QuivrButton from "@/lib/components/ui/QuivrButton/QuivrButton";
import { Knowledge } from "@/lib/types/Knowledge";

import KnowledgeItem from "./KnowledgeItem/KnowledgeItem";
import styles from "./KnowledgeTable.module.scss";

interface KnowledgeTableProps {
  knowledgeList: Knowledge[];
}

const KnowledgeTable = React.forwardRef<HTMLDivElement, KnowledgeTableProps>(
  ({ knowledgeList }, ref) => {
    const [selectedKnowledge, setSelectedKnowledge] = useState<string[]>([]);

    const handleSelect = (id: string) => {
      setSelectedKnowledge((prevSelected) =>
        prevSelected.includes(id)
          ? prevSelected.filter((selectedId) => selectedId !== id)
          : [...prevSelected, id]
      );
    };

    return (
      <div ref={ref} className={styles.knowledge_table_wrapper}>
        <div className={styles.table_header}>
          <span className={styles.title}>Uploaded Knowledge</span>
          <QuivrButton label="Clear all" iconName="delete" color="dangerous" />
        </div>
        <div className={styles.table}>
          <div className={styles.first_line}>
            <span className={styles.name}>Name</span>
            <span className={styles.actions}>Actions</span>
          </div>
          {knowledgeList.map((knowledge) => (
            <KnowledgeItem
              knowledge={knowledge}
              key={knowledge.id}
              selected={selectedKnowledge.includes(knowledge.id)}
              setSelected={() => handleSelect(knowledge.id)}
            />
          ))}
        </div>
      </div>
    );
  }
);

KnowledgeTable.displayName = "KnowledgeTable";

export default KnowledgeTable;
