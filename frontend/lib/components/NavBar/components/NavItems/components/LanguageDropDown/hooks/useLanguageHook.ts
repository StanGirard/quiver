import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

export type Language = {
  id: string;
  name: string;
};

export const useLanguageHook = (): {
    change: (newLanguage: Language) => void;
    allLanguages: Language[];
    currentLanguage: Language | null;
  } => {
  const { i18n } = useTranslation();
  const [allLanguages, setAllLanguages] = useState<Language[]>([]);
  const [currentLanguage, setCurrentLanguage] = useState<Language | null>(null);

  useEffect(() => {
    const languages = [
      { 
        id: "en",
        name: 'English'
      },
      {
        id: "es",
        name: 'Español'
      }
    ];
    
    setAllLanguages(languages);

    // Intenta obtener el idioma del localStorage
    const savedLanguage = localStorage.getItem('selectedLanguage');
    
    if (savedLanguage != null) {
      const foundLanguage = languages.find(lang => lang.id === savedLanguage);
      if (foundLanguage) {
        setCurrentLanguage(foundLanguage);
        void i18n.changeLanguage(foundLanguage.id);

        return;
      }
    }

    // Si no se encontró un idioma guardado o no es válido, establece el idioma predeterminado
    setCurrentLanguage(languages[0]);
    localStorage.setItem('selectedLanguage', languages[0].id);
  }, [i18n]);

  const change = (newLanguage: Language) => {
    setCurrentLanguage(newLanguage);
    localStorage.setItem('selectedLanguage', newLanguage.id);
    void i18n.changeLanguage(newLanguage.id);
  };

  return {
    change,
    allLanguages,
    currentLanguage
  };
};
