"use client";

import { useState } from "react";

import PageHeader from "@/lib/components/PageHeader/PageHeader";
import { Tabs } from "@/lib/components/ui/Tabs/Tabs";
import { ButtonType } from "@/lib/types/QuivrButton";
import { Tab } from "@/lib/types/Tab";

import { ManageBrains } from "./components/BrainsTabs/components/ManageBrains/ManageBrains";
import styles from "./page.module.scss";

const Studio = (): JSX.Element => {
  const [selectedTab, setSelectedTab] = useState("Manage my brains");

  const studioTabs: Tab[] = [
    {
      label: "Manage my brains",
      isSelected: selectedTab === "Manage my brains",
      onClick: () => setSelectedTab("Manage my brains"),
    },
    {
      label: "Analytics - Coming soon",
      isSelected: selectedTab === "Analytics",
      onClick: () => setSelectedTab("Analytics"),
      disabled: true,
    },
  ];

  const buttons: ButtonType[] = [
    {
      label: "Create brain",
      color: "primary",
      onClick: () => {
        console.info("create");
      },
    },
    {
      label: "Add knowledge",
      color: "primary",
      onClick: () => {
        console.info("add");
      },
    },
  ];

  return (
    <div className={styles.page_wrapper}>
      <div className={styles.page_header}>
        <PageHeader iconName="brainCircuit" label="Studio" buttons={buttons} />
      </div>
      <div className={styles.content_wrapper}>
        <Tabs tabList={studioTabs} />
        {selectedTab === "Manage my brains" && <ManageBrains />}
      </div>
    </div>
  );
};

export default Studio;
