# quivr-core package

The RAG of Quivr.com

## License 📄

This project is licensed under the Apache 2.0 License

## Installation

```bash
pip install quivr-core
```

### Use with [MegaParse](https://github.com/QuivrHQ/MegaParse)

By **default** megaparse-core uses MegaParse to parse files, in order to use it we need to either :

**Use Quivr hosted Megaparse API**
* Send email to **admin@quivr.app** with object  : "[Megaparse] API Key Request"
* Add ```MEGAPARSE_API_KEY = md-...``` in your *.env* file

**Use self hosted Megaparse API**
* Clone https://github.com/QuivrHQ/MegaParse
* Run the api with ```make dev``` in ```cd MegaParse```
* Back in quivr-core add ```MEGAPARSE_URL = http://localhost:8000``` in your env variables



