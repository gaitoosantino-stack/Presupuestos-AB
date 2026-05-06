from app import app, sync_precios_google_sheet


def main():
    with app.app_context():
        success, message, count = sync_precios_google_sheet()
    print(message)
    raise SystemExit(0 if success else 1)


if __name__ == '__main__':
    main()